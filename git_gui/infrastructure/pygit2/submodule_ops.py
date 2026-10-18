from __future__ import annotations

import logging
import os

import pygit2

from git_gui.domain.entities import Submodule
from git_gui.infrastructure.git_process import run_git
from git_gui.infrastructure.pygit2._helpers import (
    _parse_gitmodules_paths,
    _read_submodule_head_oid,
)

logger = logging.getLogger(__name__)


class SubmoduleOps:
    """Submodule listing, add/remove/set-url operations, plus the diff-
    synthesis helper that overlays uninitialized submodule changes.

    Mixin — not instantiable on its own. Relies on `self._repo` set up
    by the composite class.
    """

    _repo: pygit2.Repository  # provided by the composite

    def _detect_diverged_submodules(self) -> list[tuple[str, str, str, str]]:
        """Return ``(path, tree_oid, index_oid, actual_oid)`` for each submodule
        where at least one of the three oids differs.

        Surfaces submodule changes that pygit2's ``status()``/``diff()`` misses
        when the submodule workdir has no ``.git`` link file (an "uninitialized"
        or broken checkout). The gitdir is still found via ``_resolve_gitdir``.
        """
        if self._repo.head_is_unborn:
            return []
        result: list[tuple[str, str, str, str]] = []
        try:
            head_tree = self._repo.head.peel(pygit2.Commit).tree
            index = self._repo.index
            for sub_path in _parse_gitmodules_paths(self._repo.workdir):
                try:
                    tree_oid = str(head_tree[sub_path].id)
                except KeyError:
                    continue
                try:
                    index_oid = str(index[sub_path].id)
                except KeyError:
                    index_oid = tree_oid
                actual_oid = _read_submodule_head_oid(self._repo.workdir, sub_path)
                if actual_oid is None:
                    continue
                if tree_oid != index_oid or index_oid != actual_oid:
                    result.append((sub_path, tree_oid, index_oid, actual_oid))
        except Exception as e:
            logger.warning("Failed to detect submodule changes: %s", e)
        return result

    # ----------------------------------------------------------------- writes

    # ----- Submodules -----

    def _submodule_cli(self):
        from git_gui.infrastructure.submodule_cli import SubmoduleCli

        return SubmoduleCli(self._repo.workdir, env=self._git_env)

    def list_submodules(self) -> list[Submodule]:
        result: list[Submodule] = []
        try:
            sm_paths = list(self._repo.listall_submodules())
        except Exception as e:
            logger.warning("Failed to list submodules: %s", e)
            return result
        if not sm_paths:
            return result

        url_map = self._gitmodules_urls_by_path()

        # Get head SHAs via git ls-files -s (gitlink entries have mode 160000)
        sha_map: dict[str, str] = {}
        try:
            ls_result = run_git(
                ["git", "ls-files", "-s", "--", *sm_paths],
                cwd=self._repo.workdir,
                env=self._git_env,
            )
            for line in ls_result.stdout.splitlines():
                # Format: "160000 <sha> <stage>\t<path>"
                line_parts = line.split("\t", 1)
                if len(line_parts) == 2:
                    fields = line_parts[0].split()
                    if len(fields) >= 2 and fields[0] == "160000":
                        sha_map[line_parts[1]] = fields[1]
        except Exception as e:
            logger.warning("Failed to read submodule SHAs via git ls-files: %s", e)

        for path in sm_paths:
            url = url_map.get(path, "")
            head = sha_map.get(path)
            result.append(Submodule(path=path, url=url, head_sha=head))
        return result

    def _gitmodules_urls_by_path(self) -> dict[str, str]:
        gitmodules_path = os.path.join(self._repo.workdir, ".gitmodules")
        if not os.path.exists(gitmodules_path):
            return {}
        # Sections are keyed by submodule name ("submodule.<name>.url"), which
        # differs from the path after `add --name` or `git mv`; a section with
        # no path entry uses its name as the path.
        url_by_name: dict[str, str] = {}
        path_by_name: dict[str, str] = {}
        try:
            for entry in pygit2.Config(gitmodules_path):
                section, _, rest = entry.name.partition(".")
                name, _, key = rest.rpartition(".")
                if section != "submodule" or not name:
                    continue
                if key == "url":
                    url_by_name[name] = entry.value
                elif key == "path":
                    path_by_name[name] = entry.value
        except Exception as e:
            logger.warning("Failed to parse .gitmodules at %r: %s", gitmodules_path, e)
        return {path_by_name.get(name, name): url for name, url in url_by_name.items()}

    def add_submodule(self, path: str, url: str) -> None:
        self._submodule_cli().add(path=path, url=url)

    def remove_submodule(self, path: str) -> None:
        self._submodule_cli().remove(path)

    def set_submodule_url(self, path: str, url: str) -> None:
        self._submodule_cli().set_url(path, url)
