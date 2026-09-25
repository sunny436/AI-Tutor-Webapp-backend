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
  "UpdateMeRequest": {
    "displayName": {
      "maxLength": 80
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
