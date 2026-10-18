from __future__ import annotations

import logging
from datetime import UTC, datetime

import pygit2

from git_gui.domain.entities import Tag
from git_gui.infrastructure.git_process import run_git

logger = logging.getLogger(__name__)


def _tag_names(ls_remote_output: str) -> list[str]:
    tags: list[str] = []
    for line in ls_remote_output.strip().splitlines():
        # Format: "<hash>\trefs/tags/<name>"
        parts = line.split("\t")
        if len(parts) != 2:
            continue
        ref = parts[1]
        if not ref.startswith("refs/tags/"):
            continue
        name = ref[len("refs/tags/") :]
        # Skip dereferenced entries like "v1.0^{}"
        if name.endswith("^{}"):
            continue
        tags.append(name)
    return tags


def _annotated_tag(name: str, ref: pygit2.Reference, tag_obj: pygit2.Tag) -> Tag | None:
    peeled = ref.peel()
    if not isinstance(peeled, pygit2.Commit):
        # Some repos tag a tree or a blob (git.git, linux), which no commit row can show.
        logger.debug("Skipping tag %r of a %s", name, peeled.type_str)
        return None
    tagger = tag_obj.tagger
    return Tag(
        name=name,
        target_oid=str(peeled.id),
        is_annotated=True,
        message=tag_obj.message.strip() if tag_obj.message else None,
        tagger=f"{tagger.name} <{tagger.email}>" if tagger else None,
        timestamp=datetime.fromtimestamp(tagger.time, tz=UTC).astimezone() if tagger else None,
    )


def _lightweight_tag(name: str, ref: pygit2.Reference) -> Tag:
    return Tag(
        name=name,
        target_oid=str(ref.target),
        is_annotated=False,
        message=None,
        tagger=None,
        timestamp=None,
    )


class TagOps:
    """Tag read and write operations for the pygit2 adapter.

    Mixin — not instantiable on its own. Relies on `self._repo` set up
    by the composite class.
    """

    _repo: pygit2.Repository  # provided by the composite

    def get_tags(self) -> list[Tag]:
        tags: list[Tag] = []
        for ref_name in self._repo.references:
            if not ref_name.startswith("refs/tags/"):
                continue
            ref = self._repo.references[ref_name]
            name = ref_name[len("refs/tags/") :]
            target = self._repo.get(ref.target)
            if isinstance(target, pygit2.Tag):
                tag = _annotated_tag(name, ref, target)
            else:
                tag = _lightweight_tag(name, ref)
            if tag is not None:
                tags.append(tag)
        return tags

    def get_remote_tags(self, remote: str) -> list[str]:
        """Names of the tags on *remote*.

        Raises ``RuntimeError`` when the remote cannot be listed, so that a
        caller cannot take an unreachable remote for one without tags.
        """
        result = run_git(
            ["git", "ls-remote", "--tags", remote], cwd=self._repo.workdir, env=self._git_env
        )
        if result.returncode != 0:
            raise RuntimeError(
                result.stderr.strip() or f"git ls-remote exited with code {result.returncode}"
            )
        return _tag_names(result.stdout)

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
        self._run_cancellable_remote_git("push", remote, f"refs/tags/{name}")

    def delete_remote_tag(self, remote: str, name: str) -> None:
        self._run_cancellable_remote_git("push", remote, f":refs/tags/{name}")
