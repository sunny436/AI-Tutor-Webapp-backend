"""Learning: the learner profile, subjects and learning preferences. Every query is scoped by
the calling user's id; nothing here can read or write another user's rows.

Each resource is versioned (docs/api-contract.md, "Versioned edits"). A write takes the row
lock, compares the version it was sent, applies the change and moves the version on, all in
one transaction, so two tabs or devices can never overwrite each other unnoticed.
"""

from __future__ import annotations

import uuid
from datetime import time

from sqlalchemy import delete, func, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import LearnerProfile, LearnerSubject, LearningPreferences
from app.errors import ValidationFailed, VersionConflict
from app.learning import catalog
from app.learning.context import (
    SubjectChoice,
    TutorProgress,
    build_context,
    preference_values,
    profile_values,
    read_subjects,
    subject_choices,
)
from app.learning.tutor import build_tutor_instructions


def _as_time(value: str) -> time:
    hours, minutes = value.split(":")
    return time(int(hours), int(minutes))


class LearningService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    # ------------------------------------------------------------------ reading
    async def get_profile(self, user_id: uuid.UUID) -> LearnerProfile | None:
        return await self.db.get(LearnerProfile, user_id, populate_existing=True)

    async def get_preferences(self, user_id: uuid.UUID) -> LearningPreferences | None:
        return await self.db.get(LearningPreferences, user_id, populate_existing=True)

    async def get_subjects(self, user_id: uuid.UUID) -> tuple[int, list[LearnerSubject]]:
        profile = await self.get_profile(user_id)
        if profile is None:
            return 0, []
        return profile.subjects_version, await read_subjects(self.db, user_id)

    # ----------------------------------------------------------------- writing
    async def _locked(self, model, user_id: uuid.UUID):
        """This user's row of `model`, created with its defaults if missing, locked until commit."""
        await self.db.execute(insert(model).values(user_id=user_id).on_conflict_do_nothing())
        return await self.db.get(model, user_id, with_for_update=True, populate_existing=True)

    @staticmethod
    def _check_codes(changes: dict[str, object], current: dict[str, object], prefix: str) -> list[dict]:
        """Catalog codes: unknown ones are refused, and a deprecated one only while unchanged."""
        problems = []
        for column, entries in catalog.FIELD_LISTS.items():
            if changes.get(column) is None:  # not changed, or cleared in a preview draft
                continue
            entry = catalog.lookup(entries, changes[column])
            field = f"{prefix}{_camel(column)}"
            if entry is None:
                problems.append({"field": field, "reason": "unknown_code"})
            elif entry.deprecated and changes[column] != current.get(column):
                problems.append({"field": field, "reason": "deprecated"})
        return problems

    async def update_profile(
        self, user_id: uuid.UUID, version: int, changes: dict[str, object], reset: list[str]
    ) -> LearnerProfile | None:
        if not changes and not reset:  # nothing to do: nothing written, version unchanged
            return await self.get_profile(user_id)
        row = await self._locked(LearnerProfile, user_id)
        if row.version != version:
            await self.db.rollback()
            raise VersionConflict()
        current = profile_values(row)
        problems = self._check_codes(changes, current, "set.")
        merged = {**current, **changes, **dict.fromkeys(reset)}
        if merged.get("board_state") is not None and merged.get("board") != "state":
            problems.append({"field": "set.boardState", "reason": "requires_state_board"})
        if problems:
            await self.db.rollback()
            raise ValidationFailed("Some values are not allowed.", fields=problems)

        values = dict(changes)
        if isinstance(values.get("preferred_study_time"), str):
            values["preferred_study_time"] = _as_time(values["preferred_study_time"])
        values.update({column: ([] if column == "weak_topics" else None) for column in reset})
        await self.db.execute(
            update(LearnerProfile)
            .where(LearnerProfile.user_id == user_id)
            .values(**values, version=LearnerProfile.version + 1, updated_at=func.clock_timestamp())
        )
        await self.db.commit()
        return await self.get_profile(user_id)

    async def replace_subjects(
        self, user_id: uuid.UUID, version: int, items: list[SubjectChoice]
    ) -> tuple[int, list[LearnerSubject]]:
        profile = await self._locked(LearnerProfile, user_id)
        if profile.subjects_version != version:
            await self.db.rollback()
            raise VersionConflict()
        kept = {row.subject_code for row in await read_subjects(self.db, user_id)}
        problems = []
        for index, item in enumerate(items):
            entry = catalog.lookup(catalog.SUBJECTS, item.code)
            if entry is None:
                problems.append({"field": f"items.{index}.code", "reason": "unknown_code"})
            elif entry.deprecated and item.code not in kept:
                problems.append({"field": f"items.{index}.code", "reason": "deprecated"})
        if problems:
            await self.db.rollback()
            raise ValidationFailed("Some subjects are not allowed.", fields=problems)

        await self.db.execute(delete(LearnerSubject).where(LearnerSubject.user_id == user_id))
        if items:
            await self.db.execute(
                insert(LearnerSubject),
                [
                    {
                        "user_id": user_id,
                        "subject_code": item.code,
                        "position": position,
                        "is_priority": item.is_priority,
                        "needs_improvement": item.needs_improvement,
                    }
                    for position, item in enumerate(items)
                ],
            )
        await self.db.execute(
            update(LearnerProfile)
            .where(LearnerProfile.user_id == user_id)
            .values(subjects_version=LearnerProfile.subjects_version + 1)
        )
        await self.db.commit()
        return await self.get_subjects(user_id)

    async def update_preferences(
        self, user_id: uuid.UUID, version: int, changes: dict[str, str], reset: list[str]
    ) -> LearningPreferences | None:
        if not changes and not reset:
            return await self.get_preferences(user_id)
        row = await self._locked(LearningPreferences, user_id)
        if row.version != version:
            await self.db.rollback()
            raise VersionConflict()
        await self.db.execute(
            update(LearningPreferences)
            .where(LearningPreferences.user_id == user_id)
            .values(
                **changes,
                **dict.fromkeys(reset, "auto"),
                version=LearningPreferences.version + 1,
                updated_at=func.clock_timestamp(),
            )
        )
        await self.db.commit()
        return await self.get_preferences(user_id)

    # ------------------------------------------------------------------ preview
    async def preview_instructions(
        self,
        user_id: uuid.UUID,
        profile: dict[str, object] | None,
        subjects: list[SubjectChoice] | None,
        preferences: dict[str, str] | None,
        progress: TutorProgress | None = None,
    ) -> str:
        """The stored settings with a draft laid over them, as the tutor would be told (with
        `progress`, read by the caller). Nothing is written; unknown codes are refused like a save
        would refuse them."""
        stored = await self.get_profile(user_id)
        values = {**profile_values(stored), **(profile or {})}
        if isinstance(values.get("preferred_study_time"), str):  # a draft's "HH:MM", as a save stores it
            values["preferred_study_time"] = _as_time(values["preferred_study_time"])
        problems = self._check_codes(profile or {}, {}, "profile.") if profile else []
        problems = [p for p in problems if p["reason"] == "unknown_code"]  # a preview may show a kept, deprecated code
        if subjects is not None:
            problems += [
                {"field": f"subjects.{index}.code", "reason": "unknown_code"}
                for index, item in enumerate(subjects)
                if catalog.lookup(catalog.SUBJECTS, item.code) is None
            ]
        if problems:
            raise ValidationFailed("Some values are not allowed.", fields=problems)
        if subjects is None:
            subjects = subject_choices(await read_subjects(self.db, user_id)) if stored else []
        merged_preferences = {**preference_values(await self.get_preferences(user_id)), **(preferences or {})}
        return build_tutor_instructions(build_context(values, subjects, merged_preferences, progress))


def _camel(column: str) -> str:
    head, *rest = column.split("_")
    return head + "".join(part.title() for part in rest)
