/** The learning side of Settings: the academic catalog, the learner profile, subjects,
 * learning and tutor preferences, and the preview of what the tutor is told. */

import { callRoute } from "./http";
import type {
  AcademicCatalog,
  LearnerProfile,
  LearningPreferenceField,
  LearningPreferenceValues,
  LearningPreferences,
  SubjectItem,
  SubjectList,
  TutorPreview,
  TutorPreviewRequest,
  UpdateLearnerProfileRequest,
  VersionedEdit,
} from "./types";

/** Public and the same for everyone; codes are permanent, `deprecated` ones may only be kept. */
export function getCatalog(): Promise<AcademicCatalog> {
  return callRoute("GET /v1/catalog/academic");
}

export function getLearnerProfile(): Promise<LearnerProfile> {
  return callRoute("GET /v1/learning/profile");
}

export function updateLearnerProfile(edit: UpdateLearnerProfileRequest): Promise<LearnerProfile> {
  return callRoute("PATCH /v1/learning/profile", {
    body: { version: edit.version, set: edit.set ?? {}, reset: edit.reset ?? [] },
  });
}

export function getSubjects(): Promise<SubjectList> {
  return callRoute("GET /v1/learning/subjects");
}

/** Replaces the whole list; its order is the order shown. */
export function replaceSubjects(version: number, items: SubjectItem[]): Promise<SubjectList> {
  return callRoute("PUT /v1/learning/subjects", {
    body: {
      version,
      items: items.map((item) => ({
        code: item.code,
        isPriority: item.isPriority,
        needsImprovement: item.needsImprovement,
      })),
    },
  });
}

export function getLearningPreferences(): Promise<LearningPreferences> {
  return callRoute("GET /v1/learning/preferences");
}

export function updateLearningPreferences(
  edit: VersionedEdit<LearningPreferenceValues, LearningPreferenceField>,
): Promise<LearningPreferences> {
  return callRoute("PATCH /v1/learning/preferences", {
    body: { version: edit.version, set: edit.set ?? {}, reset: edit.reset ?? [] },
  });
}

/** What the tutor would be told with these (unsaved) edits over what is stored. Saves nothing. */
export function previewTutor(draft: TutorPreviewRequest = {}): Promise<TutorPreview> {
  return callRoute("POST /v1/learning/tutor-preview", { body: draft });
}
