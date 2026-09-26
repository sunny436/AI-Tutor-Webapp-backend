// GENERATED from docs/openapi.json by scripts/gen-contract.ts. Do not edit: run `bun run contract`.
// The backend owns these enums and limits; the web app reads them from here.

export const CONTRACT = {
  "ChangePasswordRequest": {
    "currentPassword": {
      "maxLength": 128,
      "minLength": 1
    },
    "newPassword": {
      "maxLength": 128,
      "minLength": 8
    }
  },
  "ChatRequest": {
    "message": {
      "maxLength": 16000,
      "minLength": 1
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
  "LoginRequest": {
    "password": {
      "maxLength": 128,
      "minLength": 1
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
  "ResendCodeRequest": {
    "purpose": {
      "enum": [
        "verify_email",
        "reset_password"
      ]
    }
  },
  "ResetPasswordRequest": {
    "code": {
      "pattern": "^\\d{6}$"
    },
    "newPassword": {
      "maxLength": 128,
      "minLength": 8
    }
  },
  "SignupRequest": {
    "displayName": {
      "maxLength": 80
    },
    "password": {
      "maxLength": 128,
      "minLength": 8
    }
  },
  "SubjectIn": {
    "code": {
      "maxLength": 40,
      "minLength": 1,
      "pattern": "^[a-z0-9_]+$"
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
          "longTermGoal"
        ]
      },
      "maxItems": 14
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
          "securityAlerts"
        ]
      },
      "maxItems": 4
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
  },
  "VerifyEmailRequest": {
    "code": {
      "pattern": "^\\d{6}$"
    }
  }
} as const;
