"""Importing this package registers every ORM model on Base.metadata, so
Base.metadata.create_all() (see app/database/init_db.py) knows about all of
them. Import new model modules here as they're added.
"""
from app.models.affected_component import AffectedComponent
from app.models.analysis import Analysis
from app.models.approval import Approval
from app.models.approval_rule import ApprovalRule
from app.models.change_request import ChangeRequest
from app.models.change_request_assignment import ChangeRequestAssignment
from app.models.change_request_history import ChangeRequestHistory
from app.models.change_request_version import ChangeRequestVersion
from app.models.clarification_question import ClarificationQuestion
from app.models.comment import ChangeRequestComment
from app.models.dependency import Dependency
from app.models.implementation_task import ImplementationTask
from app.models.impact_assessment import ImpactAssessment
from app.models.indexed_file import IndexedFile
from app.models.knowledge_chunk import KnowledgeChunk
from app.models.knowledge_document import KnowledgeDocument
from app.models.knowledge_evidence import KnowledgeEvidence
from app.models.notification import Notification
from app.models.repository_finding import RepositoryFinding
from app.models.repository_scan import RepositoryScan
from app.models.requirement import Requirement
from app.models.risk import Risk
from app.models.role_permission import RolePermission
from app.models.security_finding import SecurityFinding
from app.models.system_audit_log import SystemAuditLog
from app.models.system_setting import SystemSetting
from app.models.test_case import TestCase
from app.models.user import User

__all__ = [
    "User",
    "ChangeRequest",
    "Analysis",
    "Requirement",
    "AffectedComponent",
    "Dependency",
    "Risk",
    "ClarificationQuestion",
    "TestCase",
    "ImplementationTask",
    "ImpactAssessment",
    "SecurityFinding",
    # Module 12: Enterprise Workflow
    "ChangeRequestVersion",
    "ChangeRequestHistory",
    "ChangeRequestAssignment",
    "Approval",
    "ChangeRequestComment",
    "Notification",
    # Module 15: Repository Intelligence
    "RepositoryScan",
    "IndexedFile",
    "RepositoryFinding",
    # Module 16: Project Knowledge Base & RAG
    "KnowledgeDocument",
    "KnowledgeChunk",
    "KnowledgeEvidence",
    # Module 21: Administration & Configuration
    "RolePermission",
    "ApprovalRule",
    "SystemSetting",
    "SystemAuditLog",
]
