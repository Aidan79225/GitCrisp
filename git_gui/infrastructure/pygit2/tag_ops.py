from __future__ import annotations
from datetime import datetime, timezone
import logging
import subprocess

import pygit2

from git_gui.resources import subprocess_kwargs
from git_gui.domain.entities import Tag

logger = logging.getLogger(__name__)


class TagOps:
    """Tag read and write operations for the pygit2 adapter.

    Mixin — not instantiable on its own. Relies on `self._repo` set up
    by the composite class.
    """
    _repo: pygit2.Repository  # provided by the composite

    # ── METHODS COPIED VERBATIM from Pygit2Repository ─────────────────
    def get_tags(self) -> list[Tag]:
        tags: list[Tag] = []
        for ref_name in self._repo.references:
            if not ref_name.startswith("refs/tags/"):
                continue
            ref = self._repo.references[ref_name]
            name = ref_name[len("refs/tags/"):]
            target = self._repo.get(ref.target)
            if isinstance(target, pygit2.Tag):
                # Annotated tag — peel to get the commit OID
                peeled = ref.peel(pygit2.Commit)
                commit_oid = str(peeled.id)
                ts = datetime.fromtimestamp(target.tagger.time, tz=timezone.utc) if target.tagger else None
                tagger_str = f"{target.tagger.name} <{target.tagger.email}>" if target.tagger else None
                tags.append(Tag(
                    name=name,
                    target_oid=commit_oid,
                    is_annotated=True,
                    message=target.message.strip() if target.message else None,
                    tagger=tagger_str,
                    timestamp=ts,
                ))
            else:
                # Lightweight tag — target is a commit directly
                tags.append(Tag(
                    name=name,
                    target_oid=str(ref.target),
                    is_annotated=False,
                    message=None,
                    tagger=None,
                    timestamp=None,
                ))
        return tags

    def get_remote_tags(self, remote: str) -> list[str]:
        try:
            result = subprocess.run(
                ["git", "ls-remote", "--tags", remote],
                capture_output=True, text=True,
                cwd=self._repo.workdir, env=self._git_env, **subprocess_kwargs(),
            )
            if result.returncode != 0:
                return []
            tags: list[str] = []
            for line in result.stdout.strip().splitlines():
                # Format: "<hash>\trefs/tags/<name>"
                parts = line.split("\t")
                if len(parts) != 2:
                    continue
                ref = parts[1]
                if not ref.startswith("refs/tags/"):
                    continue
                name = ref[len("refs/tags/"):]
                # Skip dereferenced entries like "v1.0^{}"
                if name.endswith("^{}"):
                    continue
                tags.append(name)
            return tags
        except Exception as e:
            logger.warning("Failed to list remote tags for %r: %s", remote, e)
            return []

    def create_tag(self, name: str, oid: str, message: str | None = None) -> None:
        target = pygit2.Oid(hex=oid)
        if message:
            sig = self._get_signature()
            self._repo.create_tag(name, target, pygit2.GIT_OBJECT_COMMIT, sig, message)
        else:
            self._repo.references.create(f"refs/tags/{name}", target)

    def delete_tag(self, name: str) -> None:
        self._repo.references.delete(f"refs/tags/{name}")

    def push_tag(self, remote: str, name: str) -> None:
        self._run_git("push", remote, f"refs/tags/{name}")

    def delete_remote_tag(self, remote: str, name: str) -> None:
        self._run_git("push", remote, f":refs/tags/{name}")
