"""
config/tenant_loader.py
-----------------------
Loads tenant configuration from Python modules in config/tenants/.
Each tenant has its own .py file that exposes a TENANT dict.

Switched from JSON to Python modules — no json.load() needed.
importlib.import_module() handles discovery and loading.

Usage:
    from config.tenant_loader import TenantLoader

    loader = TenantLoader()
    tenant_ctx = loader.get("mock_tenant_a")

    # Or use the module-level singleton directly:
    from config.tenant_loader import loader
    tenant_ctx = loader.get("mock_tenant_a")
"""

import importlib
import logging
from config.tenants import TENANT_MODULES

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Required fields every tenant TENANT dict MUST have.
# Loader raises ValueError on startup if any are missing.
# ---------------------------------------------------------------------------
REQUIRED_FIELDS = [
    "tenant_id",
    "display_name",
    "channel",
    "ad_tenant_id",
    "cw_company_id",
    "cw_api_key_ref",
    "cwa_api_key_ref",
    "allowed_actions",
]

# ---------------------------------------------------------------------------
# Valid action names your bot supports.
# Any value in allowed_actions not in this set raises a warning at load time.
# ---------------------------------------------------------------------------
KNOWN_ACTIONS = {
    "CREATE_TICKET",
    "UPDATE_TICKET",
    "CHECK_STATUS",
    "RUN_DIAGNOSTICS",
    "RESET_OUTLOOK",
    "CHANGE_TIMEZONE",
    "RESTART_PRINTER",
    "CHECK_PRINTER_STATUS",
    "LIST_PRINTERS",
    "CLEAR_PRINT_QUEUE",
}


class TenantLoader:
    """
    Loads and caches tenant configs from config/tenants/*.py modules.

    Each module must expose a TENANT dict at the top level.
    The registry of which modules exist lives in config/tenants/__init__.py
    as the TENANT_MODULES list.

    Singleton-safe: instantiate once at app startup and reuse.
    Cache is in-process memory — restarts clear it (intentional).
    """

    def __init__(self):
        self._cache: dict[str, dict] = {}
        # Maps tenant_id -> module path string for fast lookup
        self._module_map: dict[str, str] = {}
        self._build_module_map()
        logger.info(
            f"TenantLoader initialised — "
            f"{len(self._module_map)} tenant(s) registered: "
            f"{list(self._module_map.keys())}"
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get(self, tenant_id: str) -> dict:
        """
        Load and return the tenant config for the given tenant_id.
        Results are cached after the first load.

        Args:
            tenant_id: e.g. "mock_tenant_a" — must match the tenant_id
                        field inside the corresponding .py module.

        Returns:
            Tenant config dict (a copy — callers cannot mutate the cache).

        Raises:
            ModuleNotFoundError: if no module is registered for this tenant_id.
            ValueError: if the module's TENANT dict is missing required fields.
        """
        if tenant_id in self._cache:
            return self._cache[tenant_id]

        config = self._load_from_module(tenant_id)
        self._validate(config)
        self._cache[tenant_id] = config

        logger.info(
            f"Tenant loaded: {tenant_id} "
            f"({config['display_name']}) "
            f"channel={config['channel']} "
            f"mock={config.get('mock', False)}"
        )
        return config

    def get_all(self) -> list[dict]:
        """
        Load and return all tenant configs from every registered module.
        Used at startup by TenantResolver to build the team_id lookup map.

        Returns:
            List of tenant config dicts.
        """
        configs = []
        for tenant_id in self._module_map:
            try:
                configs.append(self.get(tenant_id))
            except (ValueError, ImportError, AttributeError) as exc:
                # Log bad modules but don't abort — other tenants still load
                logger.error(
                    f"Skipping tenant '{tenant_id}' — "
                    f"failed to load module: {exc}"
                )
        return configs

    def reload(self, tenant_id: str) -> dict:
        """
        Force-reload a specific tenant module, bypassing cache.
        Useful during development when you edit a tenant .py file.

        Args:
            tenant_id: Tenant to reload.

        Returns:
            Fresh tenant config dict.
        """
        if tenant_id in self._cache:
            del self._cache[tenant_id]
            logger.info(f"Cache cleared for tenant: {tenant_id}")

        # Tell importlib to forget the cached module so edits are picked up
        module_path = self._module_map.get(tenant_id)
        if module_path:
            import sys
            if module_path in sys.modules:
                del sys.modules[module_path]

        return self.get(tenant_id)

    def reload_all(self) -> list[dict]:
        """Clear entire cache and reload all tenant modules."""
        import sys
        self._cache.clear()
        for module_path in self._module_map.values():
            if module_path in sys.modules:
                del sys.modules[module_path]
        logger.info("Tenant cache fully cleared — reloading all tenant modules")
        return self.get_all()

    @property
    def loaded_tenant_ids(self) -> list[str]:
        """Return list of tenant_ids currently in cache."""
        return list(self._cache.keys())

    @property
    def registered_tenant_ids(self) -> list[str]:
        """Return all tenant_ids registered in TENANT_MODULES."""
        return list(self._module_map.keys())

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _build_module_map(self) -> None:
        """
        Import each registered module just enough to read its tenant_id,
        then populate self._module_map: tenant_id -> module_path.
        """
        for module_path in TENANT_MODULES:
            try:
                module = importlib.import_module(module_path)
                tenant_id = module.TENANT.get("tenant_id")
                if not tenant_id:
                    logger.warning(
                        f"Module '{module_path}' has no tenant_id in TENANT dict — skipping."
                    )
                    continue
                self._module_map[tenant_id] = module_path
            except (ImportError, AttributeError) as exc:
                logger.error(
                    f"Cannot import tenant module '{module_path}': {exc}"
                )

    def _load_from_module(self, tenant_id: str) -> dict:
        """
        Import the tenant module and return a copy of its TENANT dict.

        Args:
            tenant_id: Tenant to load.

        Returns:
            Shallow copy of the TENANT dict from the module.

        Raises:
            ModuleNotFoundError: if tenant_id is not in the module map.
            AttributeError: if the module has no TENANT attribute.
        """
        module_path = self._module_map.get(tenant_id)

        if not module_path:
            available = list(self._module_map.keys())
            raise ModuleNotFoundError(
                f"No tenant module registered for '{tenant_id}'.\n"
                f"Available tenants: {available}\n"
                f"To add a new tenant:\n"
                f"  1. Create config/tenants/{tenant_id}.py with a TENANT dict\n"
                f"  2. Add 'config.tenants.{tenant_id}' to TENANT_MODULES "
                f"in config/tenants/__init__.py"
            )

        module = importlib.import_module(module_path)

        if not hasattr(module, "TENANT"):
            raise AttributeError(
                f"Tenant module '{module_path}' must define a TENANT dict at the top level."
            )

        # Shallow copy — prevents callers from mutating the module-level dict
        config = dict(module.TENANT)

        # Defensive check: tenant_id in dict must match what we looked up
        if config.get("tenant_id") != tenant_id:
            logger.warning(
                f"tenant_id mismatch in '{module_path}': "
                f"TENANT says '{config.get('tenant_id')}', "
                f"registry expects '{tenant_id}'. "
                f"Using registry value."
            )
            config["tenant_id"] = tenant_id

        return config

    def _validate(self, config: dict) -> None:
        """
        Validate required fields, allowed_actions content, and channel value.

        Args:
            config: Tenant config dict to validate.

        Raises:
            ValueError: on any validation failure.
        """
        tenant_id = config.get("tenant_id", "<unknown>")

        # All required fields must be present
        missing = [f for f in REQUIRED_FIELDS if f not in config]
        if missing:
            raise ValueError(
                f"Tenant '{tenant_id}' TENANT dict is missing required fields: {missing}"
            )

        # allowed_actions must be a non-empty list
        actions = config.get("allowed_actions", [])
        if not isinstance(actions, list) or len(actions) == 0:
            raise ValueError(
                f"Tenant '{tenant_id}' must have at least one entry in allowed_actions."
            )

        # Warn on unrecognised action names — catches typos early
        unknown = set(actions) - KNOWN_ACTIONS
        if unknown:
            logger.warning(
                f"Tenant '{tenant_id}' has unrecognised actions: {unknown}. "
                f"Known actions: {KNOWN_ACTIONS}"
            )

        # channel must be a recognised value
        valid_channels = {"teams", "slack", "web"}
        if config.get("channel") not in valid_channels:
            raise ValueError(
                f"Tenant '{tenant_id}' has invalid channel '{config.get('channel')}'. "
                f"Must be one of: {valid_channels}"
            )


# ---------------------------------------------------------------------------
# Module-level singleton — import and use directly anywhere in the project:
#   from config.tenant_loader import loader
#   ctx = loader.get("mock_tenant_a")
# ---------------------------------------------------------------------------
loader = TenantLoader()