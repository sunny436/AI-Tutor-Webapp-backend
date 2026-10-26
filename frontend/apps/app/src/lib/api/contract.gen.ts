// GENERATED from docs/openapi.json by scripts/gen-contract.ts. Do not edit: run `bun run contract`.
// The backend owns these enums and limits; the web app reads them from here.

export const CONTRACT = {
  "ActivityTimeOut": {
    "activity": {
      "enum": [
        "reading",
        "practice",
        "revision",
        "test"
      ]
    }
  },
  "AppearanceOut": {
    "fontSize": {
      "enum": [
        "small",
        "medium",
        "large",
        "x_large"
      ]
    },
    "theme": {
      "enum": [
        "system",
        "light",
        "dark"
      ]
    }
  },
  "AppearanceSet": {
    "fontSize": {
      "enum": [
        "small",
        "medium",
        "large",
        "x_large"
      ]
    },
    "theme": {
      "enum": [
        "system",
        "light",
        "dark"
      ]
    }
  },
  "AssessmentAnswerOut": {
    "status": {
      "enum": [
        "answered",
        "skipped"
      ]
    }
  },
  "AssessmentQuestionOut": {
    "kind": {
      "enum": [
        "mcq",
        "fill_blank"
      ]
    }
  },
  "AssessmentResponseOut": {
    "kind": {
      "enum": [
        "test",
        "exercise"
      ]
    },
    "state": {
      "enum": [
        "not_started",
        "active",
        "completed"
      ]
    }
  },
  "AssessmentResponseRequest": {
    "action": {
      "enum": [
        "answer",
        "skip"
      ]
    },
    "hash": {
      "pattern": "^[0-9a-f]{64}$"
    },
    "position": {
      "maximum": 9,
      "minimum": 0
    },
    "question": {
      "minimum": 0
    }
  },
  "ChaptersOut": {
    "reason": {
      "enum": [
        "no_class",
        "unavailable",
        "not_configured"
      ]
    }
  },
  "ChatRequest": {
    "attachmentIds": {
      "maxItems": 5
    },
    "message": {
      "maxLength": 16000,
      "minLength": 1
    },
    "mode": {
      "enum": [
        "text",
        "voice"
      ]
    },
    "speechFormat": {
      "enum": [
        "mp3",
        "opus",
        "aac"
      ]
    }
  },
  "ConceptMasteryOut": {
    "state": {
      "enum": [
        "mastered",
        "learning",
        "weak",
        "not_enough_evidence"
      ]
    }
  },
  "CreateConversationRequest": {
    "title": {
      "maxLength": 120
    }
  },
  "DeleteMeRequest": {
    "password": {
      "maxLength": 128,
      "minLength": 1
    }
  },
  "EmailChangeRequest": {
    "password": {
      "maxLength": 128,
      "minLength": 1
    }
  },
  "EmailConfirmRequest": {
    "code": {
      "pattern": "^\\d{6}$"
    }
  },
  "FeedbackOut": {
    "rating": {
      "enum": [
        "up",
        "down"
      ]
    }
  },
  "FeedbackRequest": {
    "comment": {
      "maxLength": 2000
    },
    "rating": {
      "enum": [
        "up",
        "down"
      ]
    }
  },
  "FileOut": {
    "kind": {
      "enum": [
        "pdf",
        "docx",
        "pptx",
        "xlsx",
        "csv",
        "txt",
        "md",
        "image"
      ]
    },
    "status": {
      "enum": [
        "processing",
        "ready",
        "failed",
        "stored"
      ]
    }
  },
  "LearnerProfileOut": {
    "mainGoal": {
      "enum": [
        "board_exams",
        "competitive_exam",
        "better_marks",
        "understand_concepts",
        "homework_help",
        "other"
      ]
    }
  },
  "LearnerProfileSet": {
    "academicYear": {
      "maxLength": 40,
      "minLength": 1,
      "pattern": "^[a-z0-9_]+$"
    },
    "board": {
      "maxLength": 40,
      "minLength": 1,
      "pattern": "^[a-z0-9_]+$"
    },
    "boardState": {
      "maxLength": 40,
      "minLength": 1,
      "pattern": "^[a-z0-9_]+$"
    },
    "dailyActiveMinutesGoal": {
      "maximum": 720,
      "minimum": 0
    },
    "grade": {
      "maxLength": 40,
      "minLength": 1,
      "pattern": "^[a-z0-9_]+$"
    },
    "longTermGoal": {
      "maxLength": 280,
      "minLength": 1
    },
    "mainGoal": {
      "enum": [
        "board_exams",
        "competitive_exam",
        "better_marks",
        "understand_concepts",
        "homework_help",
        "other"
      ]
    },
    "medium": {
      "maxLength": 40,
      "minLength": 1,
      "pattern": "^[a-z0-9_]+$"
    },
    "preferredStudyTime": {
      "pattern": "^([01]\\d|2[0-3]):[0-5]\\d$"
    },
    "shortTermGoal": {
      "maxLength": 280,
      "minLength": 1
    },
    "targetExam": {
      "maxLength": 80,
      "minLength": 1
    },
    "targetScorePercent": {
      "maximum": 100,
      "minimum": 0
    },
    "weakTopics": {
      "items": {
        "maxLength": 60,
        "minLength": 1
      },
      "maxItems": 10
    },
    "weeklyActiveMinutesGoal": {
      "maximum": 5040,
      "minimum": 0
    }
  },
  "LearningDayOut": {
    "intensity": {
      "maximum": 4,
      "minimum": 1
    }
  },
  "LearningEventOut": {
    "event": {
      "enum": [
        "started",
        "extended",
        "milestone"
      ]
    }
  },
  "LearningPreferencesOut": {
    "answerMode": {
      "enum": [
        "auto",
        "direct",
        "hints_first",
        "socratic"
      ]
    },
    "askBeforeAnswer": {
      "enum": [
        "auto",
        "on",
        "off"
      ]
    },
    "difficulty": {
      "enum": [
        "auto",
        "easy",
        "medium",
        "hard"
      ]
    },
    "explanationLevel": {
      "enum": [
        "auto",
        "simple",
        "standard",
        "detailed"
      ]
    },
    "highlightKeyConcepts": {
      "enum": [
        "auto",
        "on",
        "off"
      ]
    },
    "language": {
      "enum": [
        "auto",
        "english",
        "hindi",
        "hinglish"
      ]
    },
    "mistakeCorrection": {
      "enum": [
        "auto",
        "gentle",
        "direct"
      ]
    },
    "pace": {
      "enum": [
        "auto",
        "slow",
        "steady",
        "fast"
      ]
    },
    "personality": {
      "enum": [
        "auto",
        "friendly",
        "encouraging",
        "professional"
      ]
    },
    "practiceQuestions": {
      "enum": [
        "auto",
        "on",
        "off"
      ]
    },
    "realWorldExamples": {
      "enum": [
        "auto",
        "more",
        "fewer"
      ]
    },
    "responseLength": {
      "enum": [
        "auto",
        "short",
        "medium",
        "long"
      ]
    },
    "stepByStep": {
      "enum": [
        "auto",
        "on",
        "off"
      ]
    },
    "visualExplanations": {
      "enum": [
        "auto",
        "more",
        "fewer"
      ]
    }
  },
  "LearningPreferencesSet": {
    "answerMode": {
      "enum": [
        "auto",
        "direct",
        "hints_first",
        "socratic"
      ]
    },
    "askBeforeAnswer": {
      "enum": [
        "auto",
        "on",
        "off"
      ]
    },
    "difficulty": {
      "enum": [
        "auto",
        "easy",
        "medium",
        "hard"
      ]
    },
    "explanationLevel": {
      "enum": [
        "auto",
        "simple",
        "standard",
        "detailed"
      ]
    },
    "highlightKeyConcepts": {
      "enum": [
        "auto",
        "on",
        "off"
      ]
    },
    "language": {
      "enum": [
        "auto",
        "english",
        "hindi",
        "hinglish"
      ]
    },
    "mistakeCorrection": {
      "enum": [
        "auto",
        "gentle",
        "direct"
      ]
    },
    "pace": {
      "enum": [
        "auto",
        "slow",
        "steady",
        "fast"
      ]
    },
    "personality": {
      "enum": [
        "auto",
        "friendly",
        "encouraging",
        "professional"
      ]
    },
    "practiceQuestions": {
      "enum": [
        "auto",
        "on",
        "off"
      ]
    },
    "realWorldExamples": {
      "enum": [
        "auto",
        "more",
        "fewer"
      ]
    },
    "responseLength": {
      "enum": [
        "auto",
        "short",
        "medium",
        "long"
      ]
    },
    "stepByStep": {
      "enum": [
        "auto",
        "on",
        "off"
      ]
    },
    "visualExplanations": {
      "enum": [
        "auto",
        "more",
        "fewer"
      ]
    }
  },
  "MarkReadRequest": {
    "ids": {
      "maxItems": 30
    }
  },
  "MistakeConceptOut": {
    "state": {
      "enum": [
        "mastered",
        "learning",
        "weak",
        "not_enough_evidence"
      ]
    }
  },
  "MistakeOut": {
    "chosen": {
      "enum": [
        "A",
        "B",
        "C",
        "D"
      ]
    },
    "correct": {
      "enum": [
        "A",
        "B",
        "C",
        "D"
      ]
    }
  },
  "NotificationPreferencesOut": {
    "delivery": {
      "enum": [
        "active",
        "paused"
      ]
    }
  },
  "PracticeBookOut": {
    "language": {
      "enum": [
        "english",
        "hindi",
        "sanskrit"
      ]
    }
  },
  "PracticePlanOut": {
    "budgetSource": {
      "enum": [
        "goal",
        "default"
      ]
    }
  },
  "PracticeTaskOut": {
    "kind": {
      "enum": [
        "revise",
        "strengthen",
        "learn"
      ]
    },
    "language": {
      "enum": [
        "english",
        "hindi",
        "sanskrit"
      ]
    },
    "reason": {
      "enum": [
        "overdue",
        "due",
        "weak_concept",
        "next_topic",
        "start_here"
      ]
    }
  },
  "PracticeTopicsOut": {
    "language": {
      "enum": [
        "english",
        "hindi"
      ]
    },
    "reason": {
      "enum": [
        "no_class",
        "no_questions"
      ]
    }
  },
  "ProfileSet": {
    "displayName": {
      "maxLength": 80,
      "minLength": 1
    },
    "timezone": {
      "maxLength": 64
    }
  },
  "RecentSessionOut": {
    "activities": {
      "items": {
        "enum": [
          "reading",
          "practice",
          "revision",
          "test"
        ]
      }
    },
    "endReason": {
      "enum": [
        "ended",
        "stale",
        "limit"
      ]
    },
    "status": {
      "enum": [
        "active",
        "paused",
        "ended"
      ]
    }
  },
  "RenameConversationRequest": {
    "title": {
      "maxLength": 120,
      "minLength": 1
    }
  },
  "ReplaceSubjectsRequest": {
    "items": {
      "maxItems": 15
    },
    "version": {
      "minimum": 0
    }
  },
  "RevisionOut": {
    "state": {
      "enum": [
        "overdue",
        "due",
        "done",
        "upcoming"
      ]
    }
  },
  "SegmentOut": {
    "activity": {
      "enum": [
        "reading",
        "practice",
        "revision",
        "test"
      ]
    },
    "kind": {
      "enum": [
        "study",
        "paused"
      ]
    }
  },
  "SpeechRequest": {
    "format": {
      "enum": [
        "mp3",
        "opus",
        "aac"
      ]
    },
    "text": {
      "maxLength": 600,
      "minLength": 1
    }
  },
  "StudyContextChangeIn": {
    "activity": {
      "enum": [
        "reading",
        "practice",
        "revision",
        "test"
      ]
    },
    "chapterId": {
      "maxLength": 120
    },
    "subject": {
      "maxLength": 40
    }
  },
  "StudySessionOut": {
    "endReason": {
      "enum": [
        "ended",
        "stale",
        "limit"
      ]
    },
    "status": {
      "enum": [
        "active",
        "paused",
        "ended"
      ]
    }
  },
  "StudyStartIn": {
    "activity": {
      "enum": [
        "reading",
        "practice",
        "revision",
        "test"
      ]
    },
    "chapterId": {
      "maxLength": 120
    },
    "subject": {
      "maxLength": 40
    }
  },
  "SubjectIn": {
    "code": {
      "maxLength": 40,
      "minLength": 1,
      "pattern": "^[a-z0-9_]+$"
    }
  },
  "SubjectMasteryOut": {
    "language": {
      "enum": [
        "english",
        "hindi",
        "sanskrit"
      ]
    }
  },
  "SupportRequestIn": {
    "kind": {
      "enum": [
        "question",
        "bug",
        "feedback",
        "account"
      ]
    },
    "message": {
      "maxLength": 4000,
      "minLength": 10
    },
    "page": {
      "maxLength": 200,
      "pattern": "^/[^\\s]*$"
    },
    "subject": {
      "maxLength": 120,
      "minLength": 1
    }
  },
  "SupportRequestOut": {
    "kind": {
      "enum": [
        "question",
        "bug",
        "feedback",
        "account"
      ]
    },
    "status": {
      "enum": [
        "open",
        "closed"
      ]
    }
  },
  "TopicMasteryOut": {
    "state": {
      "enum": [
        "mastered",
        "learning",
        "weak",
        "not_enough_evidence"
      ]
    }
  },
  "TutorPreviewRequest": {
    "subjects": {
      "maxItems": 15
    }
  },
  "UnsubscribeRequest": {
    "token": {
      "maxLength": 300,
      "minLength": 10
    }
  },
  "UpdateAppearanceRequest": {
    "reset": {
      "items": {
        "enum": [
          "theme",
          "fontSize",
          "highContrast",
          "reduceMotion",
          "readingComfort",
          "showStreak"
        ]
      },
      "maxItems": 6
    },
    "version": {
      "minimum": 0
    }
  },
  "UpdateLearnerProfileRequest": {
    "reset": {
      "items": {
        "enum": [
          "grade",
          "board",
          "boardState",
          "medium",
          "academicYear",
          "mainGoal",
          "targetExam",
          "targetScorePercent",
          "weakTopics",
          "dailyActiveMinutesGoal",
          "weeklyActiveMinutesGoal",
          "preferredStudyTime",
          "shortTermGoal",
          "longTermGoal",
          "examDate"
        ]
      },
      "maxItems": 15
    },
    "version": {
      "minimum": 0
    }
  },
  "UpdateLearningPreferencesRequest": {
    "reset": {
      "items": {
        "enum": [
          "language",
          "explanationLevel",
          "pace",
          "difficulty",
          "realWorldExamples",
          "visualExplanations",
          "personality",
          "responseLength",
          "answerMode",
          "stepByStep",
          "askBeforeAnswer",
          "practiceQuestions",
          "mistakeCorrection",
          "highlightKeyConcepts"
        ]
      },
      "maxItems": 14
    },
    "version": {
      "minimum": 0
    }
  },
  "UpdateMeRequest": {
    "displayName": {
      "maxLength": 80
    }
  },
  "UpdateNotificationPreferencesRequest": {
    "reset": {
      "items": {
        "enum": [
          "dailyReminder",
          "streakWarning",
          "weeklySummary",
          "securityAlerts",
          "inAppReminders"
        ]
      },
      "maxItems": 5
    },
    "version": {
      "minimum": 0
    }
  },
  "UpdateProfileRequest": {
    "reset": {
      "items": {
        "enum": [
          "displayName",
          "timezone"
        ]
      },
      "maxItems": 2
    },
    "version": {
      "minimum": 0
    }
  }
} as const;
