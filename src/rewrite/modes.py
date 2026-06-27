from enum import Enum


class RewriteMode(Enum):
    SMART = "smart"
    CLEAN_GRAMMAR = "clean_grammar"
    STRUCTURED_NOTES = "structured_notes"
    CONVERT_TO_PRD = "convert_to_prd"
    PROFESSIONAL_EMAIL = "professional_email"
    LINKEDIN_POST = "linkedin_post"
    DEVELOPER_COMMENT = "developer_comment"
    BRAIN_DUMP = "brain_dump"

    @property
    def display_name(self) -> str:
        names = {
            RewriteMode.SMART: "Smart (auto-format)",
            RewriteMode.CLEAN_GRAMMAR: "Clean & Fix Grammar",
            RewriteMode.STRUCTURED_NOTES: "Structured Notes",
            RewriteMode.CONVERT_TO_PRD: "Convert to PRD",
            RewriteMode.PROFESSIONAL_EMAIL: "Professional Email",
            RewriteMode.LINKEDIN_POST: "LinkedIn Post",
            RewriteMode.DEVELOPER_COMMENT: "Developer Comment",
            RewriteMode.BRAIN_DUMP: "Brain Dump -> Organized Output",
        }
        return names[self]
