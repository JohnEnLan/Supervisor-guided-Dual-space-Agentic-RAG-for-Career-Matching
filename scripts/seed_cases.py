from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.db.pool import close_pool
from app.memory.case_base import CareerCase, upsert_career_case


DEFAULT_CASES = [
    CareerCase(
        case_id="case-001",
        background_type="business_undergraduate_with_python_dashboard_project",
        target_role="Data Analyst Intern",
        successful_resume_features=[
            "dashboard project framed with business impact",
            "SQL coursework listed near target role",
        ],
        missing_skills_before=["advanced SQL", "portfolio case study"],
        application_outcome="interview_1",
        recommended_bridge_roles=["Business Analyst Intern", "Operations Analyst Intern"],
    ),
    CareerCase(
        case_id="case-002",
        background_type="marketing_coordinator_with_content_and_events",
        target_role="Marketing Coordinator",
        successful_resume_features=[
            "campaign coordination bullets grouped under marketing",
            "content samples linked as anonymized portfolio category",
        ],
        missing_skills_before=["marketing analytics", "CRM reporting"],
        application_outcome="passed_screen",
        recommended_bridge_roles=["Communications Assistant", "Office Marketing Coordinator"],
    ),
    CareerCase(
        case_id="case-003",
        background_type="software_support_candidate_transitioning_to_engineering",
        target_role="Software Engineer",
        successful_resume_features=[
            "debugging examples translated into engineering language",
            "API project placed before customer support history",
        ],
        missing_skills_before=["system design basics", "automated testing"],
        application_outcome="interview_1",
        recommended_bridge_roles=["Software Support Specialist", "Junior Backend Developer"],
    ),
    CareerCase(
        case_id="case-004",
        background_type="healthcare_worker_with_patient_care_experience",
        target_role="Registered Nurse",
        successful_resume_features=[
            "patient care responsibilities grouped by clinical skill",
            "certifications and shift experience made scannable",
        ],
        missing_skills_before=["specialty unit keywords", "quantified caseload"],
        application_outcome="passed_screen",
        recommended_bridge_roles=["Clinical Assistant", "Care Coordinator"],
    ),
    CareerCase(
        case_id="case-005",
        background_type="property_operations_candidate_with_facilities_background",
        target_role="Commercial Property Manager",
        successful_resume_features=[
            "tenant communication examples tied to operations outcomes",
            "maintenance coordination described with vendor management",
        ],
        missing_skills_before=["lease administration terminology", "budget ownership"],
        application_outcome="interview_1",
        recommended_bridge_roles=["Assistant Property Manager", "Building Coordinator"],
    ),
    CareerCase(
        case_id="case-006",
        background_type="legal_assistant_progressing_to_transactional_support",
        target_role="Transactional Legal Assistant",
        successful_resume_features=[
            "document review experience grouped by matter type",
            "deadline and filing accuracy emphasized",
        ],
        missing_skills_before=["contract lifecycle tools", "deal closing vocabulary"],
        application_outcome="passed_screen",
        recommended_bridge_roles=["Legal Secretary", "Contracts Administrator"],
    ),
    CareerCase(
        case_id="case-007",
        background_type="restaurant_shift_lead_moving_to_operations_management",
        target_role="Assistant Restaurant Manager",
        successful_resume_features=[
            "staff scheduling and inventory examples made explicit",
            "customer escalation handling written as leadership evidence",
        ],
        missing_skills_before=["profit and loss exposure", "labor cost metrics"],
        application_outcome="offer",
        recommended_bridge_roles=["Shift Supervisor", "Hospitality Operations Coordinator"],
    ),
    CareerCase(
        case_id="case-008",
        background_type="architecture_graduate_with_project_documentation",
        target_role="Project Architect",
        successful_resume_features=[
            "construction document experience placed before design interests",
            "software tools listed by project stage",
        ],
        missing_skills_before=["site coordination evidence", "code compliance keywords"],
        application_outcome="interview_1",
        recommended_bridge_roles=["Architectural Designer", "Project Coordinator"],
    ),
    CareerCase(
        case_id="case-009",
        background_type="field_service_technician_with_refrigeration_repair",
        target_role="HVAC Technician",
        successful_resume_features=[
            "diagnostic repair examples grouped by equipment type",
            "safety and customer communication included",
        ],
        missing_skills_before=["EPA certification keywords", "preventive maintenance logs"],
        application_outcome="passed_screen",
        recommended_bridge_roles=["Service Technician", "Maintenance Technician"],
    ),
    CareerCase(
        case_id="case-010",
        background_type="finance_sales_candidate_with_client_pipeline_experience",
        target_role="Mortgage Loan Officer",
        successful_resume_features=[
            "lead generation results written as pipeline metrics",
            "client consultation examples moved near top",
        ],
        missing_skills_before=["loan product terminology", "compliance awareness"],
        application_outcome="interview_1",
        recommended_bridge_roles=["Loan Coordinator", "Financial Services Sales"],
    ),
    CareerCase(
        case_id="case-011",
        background_type="administrative_coordinator_with_nonprofit_operations",
        target_role="Administrative Coordinator",
        successful_resume_features=[
            "calendar and records work connected to team throughput",
            "stakeholder coordination examples made concise",
        ],
        missing_skills_before=["database reporting", "grant support vocabulary"],
        application_outcome="passed_screen",
        recommended_bridge_roles=["Administrative Assistant", "Program Assistant"],
    ),
    CareerCase(
        case_id="case-012",
        background_type="content_writer_with_media_production_experience",
        target_role="Communications Writer",
        successful_resume_features=[
            "writing samples grouped by audience and channel",
            "editing process described with publication cadence",
        ],
        missing_skills_before=["SEO basics", "analytics reporting"],
        application_outcome="interview_1",
        recommended_bridge_roles=["Content Assistant", "Producer Assistant"],
    ),
    CareerCase(
        case_id="case-013",
        background_type="food_operations_candidate_with_planning_and_quality_focus",
        target_role="Production Planner",
        successful_resume_features=[
            "scheduling examples tied to supply and quality constraints",
            "food safety vocabulary made explicit",
        ],
        missing_skills_before=["ERP exposure", "forecast accuracy metrics"],
        application_outcome="passed_screen",
        recommended_bridge_roles=["Operations Coordinator", "Quality Assistant"],
    ),
    CareerCase(
        case_id="case-014",
        background_type="student_affairs_candidate_with_event_leadership",
        target_role="Student Organization Coordinator",
        successful_resume_features=[
            "event planning evidence grouped by audience size",
            "cross-cultural facilitation examples highlighted",
        ],
        missing_skills_before=["assessment reporting", "budget management"],
        application_outcome="interview_1",
        recommended_bridge_roles=["Program Coordinator", "Event Assistant"],
    ),
    CareerCase(
        case_id="case-015",
        background_type="mental_health_support_candidate_with_client_service",
        target_role="Mental Health Counselor Assistant",
        successful_resume_features=[
            "client intake support described with boundaries",
            "active listening and case note examples kept evidence-based",
        ],
        missing_skills_before=["licensure path clarity", "treatment planning keywords"],
        application_outcome="passed_screen",
        recommended_bridge_roles=["Behavioral Health Assistant", "Care Navigator"],
    ),
]


async def seed_default_cases(*, limit: int | None = None, embed: bool = True) -> int:
    cases = DEFAULT_CASES[:limit] if limit else DEFAULT_CASES
    for case in cases:
        await upsert_career_case(case, embed_if_missing=embed)
    return len(cases)


async def _main_async(args: argparse.Namespace) -> None:
    try:
        count = await seed_default_cases(limit=args.limit, embed=not args.skip_embeddings)
        print(json.dumps({"seeded_cases": count, "embedded": not args.skip_embeddings}))
    finally:
        await close_pool()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Seed 10-20 anonymized career cases for P1 dual-space memory demo."
    )
    parser.add_argument("--limit", type=int)
    parser.add_argument(
        "--skip-embeddings",
        action="store_true",
        help="Insert anonymous cases without Qwen embeddings.",
    )
    args = parser.parse_args()
    asyncio.run(_main_async(args))


if __name__ == "__main__":
    main()
