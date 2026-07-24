"""Static file server with SPA index.html fallback for client-side routes."""

from __future__ import annotations

import anyio
from starlette.exceptions import HTTPException
from starlette.staticfiles import StaticFiles


class SPAStaticFiles(StaticFiles):
    """Serve built web/dist; unknown GET paths return index.html for React Router."""

    async def get_response(self, path: str, scope):
        try:
            return await super().get_response(path, scope)
        except HTTPException as exc:
            if exc.status_code != 404 or not self.html:
                raise
            index_path, stat_result = await anyio.to_thread.run_sync(
                self.lookup_path,
                "index.html",
            )
            if stat_result is None:
                raise
            return self.file_response(index_path, stat_result, scope)
