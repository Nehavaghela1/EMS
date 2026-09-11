"""Seed rich, realistic, company-unique projects and tasks for all 6 active companies."""
import uuid
from datetime import date, datetime, timedelta
from decimal import Decimal

from app.db.session import SessionLocal
from app.db.rls import bind_tenant_to_session
from app.modules.identity.models import Company, User, UserRole
from app.modules.hr.models import Employee
from app.modules.projects.models import (
    Project, ProjectMember, Task, Milestone, TimeEntry
)

COMPANIES_DATA = {
    "Infiria Systems": {
        "projects": [
            {
                "name": "EMS Enterprise 2.0",
                "code": "EMS-V2",
                "client_name": "Internal Platform",
                "status": "active",
                "budget": Decimal("650000.00"),
                "description": "Comprehensive multi-tenant human resource and project ERP platform revamp.",
                "milestones": [
                    ("Alpha Architecture & Multi-Tenancy Core", 100, "completed"),
                    ("HR & Payroll Automation Module", 100, "completed"),
                    ("Project Workspace & Timesheets", 75, "in_progress"),
                    ("SOC2 Type II Security Compliance & Audit", 20, "pending"),
                ],
                "tasks": [
                    {
                        "title": "PostgreSQL Row Level Security Enforcement",
                        "description": "Verify RLS policies with automated cross-tenant leak tests",
                        "status": "done",
                        "priority": "critical",
                        "estimated_hours": Decimal("28.00"),
                        "hours": Decimal("28.00"),
                    },
                    {
                        "title": "Interactive Kanban & Board Polish",
                        "description": "Ensure uniform column dimensions and smooth state drag-and-drop",
                        "status": "in_progress",
                        "priority": "high",
                        "estimated_hours": Decimal("24.00"),
                        "hours": Decimal("16.50"),
                    },
                    {
                        "title": "Automated Multi-Tenant Backup Pipeline",
                        "description": "Setup automated point-in-time recovery and snapshot testing",
                        "status": "review",
                        "priority": "medium",
                        "estimated_hours": Decimal("18.00"),
                        "hours": Decimal("14.00"),
                    },
                    {
                        "title": "Biometric Attendance Device Sync Agent",
                        "description": "Connect ZKTeco on-premise attendance hardware to cloud webhook",
                        "status": "todo",
                        "priority": "low",
                        "estimated_hours": Decimal("32.00"),
                        "hours": Decimal("0.00"),
                    },
                ],
            },
            {
                "name": "Infiria Mobile Suite",
                "code": "INF-MOB",
                "client_name": "Global Retail Partners",
                "status": "active",
                "budget": Decimal("420000.00"),
                "description": "Native iOS & Android enterprise employee portal with offline geo-fenced check-ins.",
                "milestones": [
                    ("Offline Sync SQLite Architecture", 100, "completed"),
                    ("Biometric Face Recognition Module", 80, "in_progress"),
                    ("App Store & Play Store Release", 10, "pending"),
                ],
                "tasks": [
                    {
                        "title": "Push Notification Hub Integration",
                        "description": "Integrate Firebase Cloud Messaging and APNs for real-time leave approvals",
                        "status": "done",
                        "priority": "high",
                        "estimated_hours": Decimal("20.00"),
                        "hours": Decimal("19.50"),
                    },
                    {
                        "title": "Geofencing & Mock Location Detection",
                        "description": "Prevent spoofing in employee mobile check-ins",
                        "status": "in_progress",
                        "priority": "critical",
                        "estimated_hours": Decimal("36.00"),
                        "hours": Decimal("22.00"),
                    },
                    {
                        "title": "Dark Mode & High-Contrast Theme Support",
                        "description": "Implement accessible WCAG 2.1 AA compliant color schemes",
                        "status": "review",
                        "priority": "low",
                        "estimated_hours": Decimal("12.00"),
                        "hours": Decimal("10.00"),
                    },
                    {
                        "title": "Battery Drain Optimization in Background Tracking",
                        "description": "Optimize location listener to consume under 3% daily battery",
                        "status": "todo",
                        "priority": "medium",
                        "estimated_hours": Decimal("16.00"),
                        "hours": Decimal("0.00"),
                    },
                ],
            },
            {
                "name": "AI Workflow & HR Copilot",
                "code": "INF-AI",
                "client_name": "Enterprise Innovation Lab",
                "status": "planning",
                "budget": Decimal("280000.00"),
                "description": "Generative assistant for payroll inquiries, resume scoring, and policy question-answering.",
                "milestones": [
                    ("Document Embedding Pipeline", 60, "in_progress"),
                    ("Fine-tuned LLM Evaluation Benchmarks", 0, "pending"),
                ],
                "tasks": [
                    {
                        "title": "Vector Embeddings for Company Handbook",
                        "description": "Chunk policy documents and store vectors in pgvector",
                        "status": "in_progress",
                        "priority": "high",
                        "estimated_hours": Decimal("30.00"),
                        "hours": Decimal("14.00"),
                    },
                    {
                        "title": "Privacy Guardrail & PII Masking Filter",
                        "description": "Mask salaries and personal employee identifiers prior to LLM calls",
                        "status": "todo",
                        "priority": "critical",
                        "estimated_hours": Decimal("25.00"),
                        "hours": Decimal("0.00"),
                    },
                    {
                        "title": "Chat UI Widget with Streaming Responses",
                        "description": "Build SSE (Server-Sent Events) interface for instant answers",
                        "status": "todo",
                        "priority": "medium",
                        "estimated_hours": Decimal("18.00"),
                        "hours": Decimal("0.00"),
                    },
                ],
            },
        ],
    },
    "NexusPay Fintech": {
        "projects": [
            {
                "name": "Instant UPI Payouts Gateway",
                "code": "UPI-GATE",
                "client_name": "National Payments Consortium",
                "status": "active",
                "budget": Decimal("950000.00"),
                "description": "Sub-second batch UPI disbursement engine handling over 5,000 TPS with automated reconciliation.",
                "milestones": [
                    ("NPCI Switch Direct Connectivity", 100, "completed"),
                    ("High-Throughput Queue Pipeline (Kafka)", 90, "in_progress"),
                    ("Disaster Recovery Site Live Drill", 30, "pending"),
                ],
                "tasks": [
                    {
                        "title": "Idempotency Lock & Double-Spend Protection",
                        "description": "Implement Redis distributed lock with SHA-256 transaction hashing",
                        "status": "done",
                        "priority": "critical",
                        "estimated_hours": Decimal("35.00"),
                        "hours": Decimal("35.00"),
                    },
                    {
                        "title": "Auto-Retry Engine for Flaky Bank Switches",
                        "description": "Exponential backoff and circuit breaker for unresponsive partner nodes",
                        "status": "in_progress",
                        "priority": "high",
                        "estimated_hours": Decimal("28.00"),
                        "hours": Decimal("18.00"),
                    },
                    {
                        "title": "VPA Verification Batch Endpoint",
                        "description": "Pre-validate UPI IDs before payout execution",
                        "status": "review",
                        "priority": "medium",
                        "estimated_hours": Decimal("16.00"),
                        "hours": Decimal("15.00"),
                    },
                    {
                        "title": "RBI Payout Audit Trail Logging",
                        "description": "Write tamper-proof ledger entries to WORM storage",
                        "status": "todo",
                        "priority": "critical",
                        "estimated_hours": Decimal("22.00"),
                        "hours": Decimal("0.00"),
                    },
                ],
            },
            {
                "name": "Automated KYC & AML Flow",
                "code": "KYC-AUTO",
                "client_name": "Apex Microfinance Group",
                "status": "active",
                "budget": Decimal("520000.00"),
                "description": "Instant Aadhaar, PAN, and video KYC verification pipeline with liveness check.",
                "milestones": [
                    ("Government Portal API Integration", 100, "completed"),
                    ("Optical Character Recognition (OCR) Engine", 85, "in_progress"),
                    ("AML Politically Exposed Persons (PEP) Scans", 40, "pending"),
                ],
                "tasks": [
                    {
                        "title": "Aadhaar Masking & Vault Encryption",
                        "description": "Store UIDAI compliant masked Aadhaar copies in HSM-backed store",
                        "status": "done",
                        "priority": "critical",
                        "estimated_hours": Decimal("30.00"),
                        "hours": Decimal("30.00"),
                    },
                    {
                        "title": "Real-time Face Match Engine",
                        "description": "Compare selfie with government ID photo with 99.4% accuracy threshold",
                        "status": "in_progress",
                        "priority": "high",
                        "estimated_hours": Decimal("40.00"),
                        "hours": Decimal("26.00"),
                    },
                    {
                        "title": "Sanctions & PEP Database Matcher",
                        "description": "Fuzzy string search against OFAC and UN sanction lists",
                        "status": "review",
                        "priority": "high",
                        "estimated_hours": Decimal("20.00"),
                        "hours": Decimal("18.00"),
                    },
                    {
                        "title": "Mobile OTP Re-verification on Address Edit",
                        "description": "Mandatory 2FA challenge when onboarding address changes",
                        "status": "todo",
                        "priority": "medium",
                        "estimated_hours": Decimal("12.00"),
                        "hours": Decimal("0.00"),
                    },
                ],
            },
            {
                "name": "Fraud Detection ML Pipeline",
                "code": "FRAUD-ML",
                "client_name": "Internal Risk Division",
                "status": "planning",
                "budget": Decimal("380000.00"),
                "description": "Streaming anomaly detection detecting velocity surges, card testing, and device fingerprint spoofing.",
                "milestones": [
                    ("Feature Store & Historic Dataset Preparation", 40, "in_progress"),
                    ("Real-time Scoring Microservice (<15ms latency)", 0, "pending"),
                ],
                "tasks": [
                    {
                        "title": "Device Fingerprint Telemetry Collector",
                        "description": "Collect canvas hash, WebGL render stats, and browser entropy securely",
                        "status": "in_progress",
                        "priority": "high",
                        "estimated_hours": Decimal("24.00"),
                        "hours": Decimal("11.00"),
                    },
                    {
                        "title": "Velocity Counter Aggregation with Redis Streams",
                        "description": "Track card attempts per IP over sliding 1-minute windows",
                        "status": "todo",
                        "priority": "critical",
                        "estimated_hours": Decimal("28.00"),
                        "hours": Decimal("0.00"),
                    },
                ],
            },
        ],
    },
    "Aether Cloud Labs": {
        "projects": [
            {
                "name": "Kubernetes Multi-Tenant Auto-scaler",
                "code": "K8S-SCALE",
                "client_name": "SaaS Platform Partners",
                "status": "active",
                "budget": Decimal("680000.00"),
                "description": "Predictive HPA and cluster autoscaler cutting cloud compute costs by 42% on AWS & GCP.",
                "milestones": [
                    ("Custom Metric Exporter DaemonSet", 100, "completed"),
                    ("Predictive Workload ML Model", 70, "in_progress"),
                    ("Multi-Region Failover Controller", 25, "pending"),
                ],
                "tasks": [
                    {
                        "title": "eBPF Pod Resource Monitor",
                        "description": "Capture kernel-level CPU and memory spikes without sidecar injection",
                        "status": "done",
                        "priority": "critical",
                        "estimated_hours": Decimal("32.00"),
                        "hours": Decimal("32.00"),
                    },
                    {
                        "title": "Spot Instance Graceful Drain Webhook",
                        "description": "Handle AWS EC2 2-minute spot termination warnings automatically",
                        "status": "in_progress",
                        "priority": "high",
                        "estimated_hours": Decimal("24.00"),
                        "hours": Decimal("15.50"),
                    },
                    {
                        "title": "Prometheus Metric Downsampling",
                        "description": "Downsample older telemetry to Thanos long-term object storage",
                        "status": "review",
                        "priority": "medium",
                        "estimated_hours": Decimal("14.00"),
                        "hours": Decimal("13.00"),
                    },
                    {
                        "title": "Terraform Module for Multi-AZ EKS Provisioning",
                        "description": "Standardize cluster infrastructure with security best practices",
                        "status": "todo",
                        "priority": "low",
                        "estimated_hours": Decimal("20.00"),
                        "hours": Decimal("0.00"),
                    },
                ],
            },
            {
                "name": "Edge Gateway Envoy Service",
                "code": "EDGE-GW",
                "client_name": "Global Telecom Consortium",
                "status": "active",
                "budget": Decimal("450000.00"),
                "description": "High performance Rust/Envoy API Gateway with distributed rate-limiting and JWT validation.",
                "milestones": [
                    ("Envoy Filter WebAssembly Plugins", 90, "in_progress"),
                    ("Global Anycast DNS Load Balancing", 50, "in_progress"),
                ],
                "tasks": [
                    {
                        "title": "WASM Token Validation Filter",
                        "description": "Validate RS256 JWT tokens directly in Envoy data plane",
                        "status": "done",
                        "priority": "high",
                        "estimated_hours": Decimal("26.00"),
                        "hours": Decimal("26.00"),
                    },
                    {
                        "title": "Distributed Token Bucket Rate Limiting",
                        "description": "Synchronize rate-limits across 12 edge points-of-presence",
                        "status": "in_progress",
                        "priority": "critical",
                        "estimated_hours": Decimal("30.00"),
                        "hours": Decimal("18.00"),
                    },
                    {
                        "title": "gRPC Web Proxy Integration",
                        "description": "Enable frontend browser clients to stream RPCs smoothly",
                        "status": "todo",
                        "priority": "medium",
                        "estimated_hours": Decimal("16.00"),
                        "hours": Decimal("0.00"),
                    },
                ],
            },
            {
                "name": "Zero-Trust Perimeter Enforcer",
                "code": "ZT-NET",
                "client_name": "Internal Security Ops",
                "status": "planning",
                "budget": Decimal("320000.00"),
                "description": "WireGuard based software-defined perimeter replacing traditional corporate VPNs.",
                "milestones": [
                    ("WireGuard Key Exchange Protocol", 30, "in_progress"),
                    ("Device Posture Evaluation Agent", 0, "pending"),
                ],
                "tasks": [
                    {
                        "title": "macOS & Linux WireGuard Client Prototype",
                        "description": "Build userland client with seamless SSO authentication",
                        "status": "in_progress",
                        "priority": "high",
                        "estimated_hours": Decimal("32.00"),
                        "hours": Decimal("12.00"),
                    },
                    {
                        "title": "Network Micro-segmentation Rule Engine",
                        "description": "Define granular policy rules per developer role and cluster environment",
                        "status": "todo",
                        "priority": "medium",
                        "estimated_hours": Decimal("24.00"),
                        "hours": Decimal("0.00"),
                    },
                ],
            },
        ],
    },
    "Zenith Health Tech": {
        "projects": [
            {
                "name": "Telehealth Video Consult Portal",
                "code": "TELE-MED",
                "client_name": "Apollo Care Hospitals",
                "status": "active",
                "budget": Decimal("780000.00"),
                "description": "HIPAA compliant WebRTC end-to-end encrypted doctor-patient video consultations with e-prescriptions.",
                "milestones": [
                    ("WebRTC P2P & SFU Server Infra", 100, "completed"),
                    ("Doctor Digital Signature & Prescription Flow", 85, "in_progress"),
                    ("Patient Medical History PDF Importer", 40, "pending"),
                ],
                "tasks": [
                    {
                        "title": "WebRTC End-to-End Encryption Audit",
                        "description": "Certify media stream encryption compliance for HIPAA standards",
                        "status": "done",
                        "priority": "critical",
                        "estimated_hours": Decimal("28.00"),
                        "hours": Decimal("28.00"),
                    },
                    {
                        "title": "Digital Drug Database & Interaction Warnings",
                        "description": "Alert physicians of contraindications when prescribing multiple medicines",
                        "status": "in_progress",
                        "priority": "high",
                        "estimated_hours": Decimal("34.00"),
                        "hours": Decimal("20.00"),
                    },
                    {
                        "title": "Low Bandwidth Video Fallback Protocol",
                        "description": "Automatically transition to audio-only if connection drops below 150kbps",
                        "status": "review",
                        "priority": "medium",
                        "estimated_hours": Decimal("18.00"),
                        "hours": Decimal("16.00"),
                    },
                    {
                        "title": "SMS Appointment Reminder Bot",
                        "description": "Send localized WhatsApp & SMS links 15 minutes before appointments",
                        "status": "todo",
                        "priority": "low",
                        "estimated_hours": Decimal("12.00"),
                        "hours": Decimal("0.00"),
                    },
                ],
            },
            {
                "name": "EHR HL7 FHIR Interoperability",
                "code": "EHR-FHIR",
                "client_name": "Metropolis Diagnostic Network",
                "status": "active",
                "budget": Decimal("540000.00"),
                "description": "Standardized electronic health record exchange connecting diagnostic labs with hospital EHR systems.",
                "milestones": [
                    ("FHIR R4 Resource Mapping Engine", 90, "in_progress"),
                    ("Lab Diagnostic Report Ingestion Pipeline", 60, "in_progress"),
                ],
                "tasks": [
                    {
                        "title": "Patient Resource Mapping & Deduplication",
                        "description": "Match incoming HL7 records by National Health ID and DOB",
                        "status": "done",
                        "priority": "high",
                        "estimated_hours": Decimal("24.00"),
                        "hours": Decimal("24.00"),
                    },
                    {
                        "title": "Diagnostic Report PDF Parser",
                        "description": "Extract blood test panels and lipid values via regex and OCR",
                        "status": "in_progress",
                        "priority": "critical",
                        "estimated_hours": Decimal("30.00"),
                        "hours": Decimal("17.00"),
                    },
                    {
                        "title": "Audit Trail for Patient Record Access",
                        "description": "Strict immutable logs for every clinician record view",
                        "status": "todo",
                        "priority": "critical",
                        "estimated_hours": Decimal("18.00"),
                        "hours": Decimal("0.00"),
                    },
                ],
            },
            {
                "name": "Patient Remote Vitals Monitoring",
                "code": "RPM-VIT",
                "client_name": "Cardiac Care Foundation",
                "status": "planning",
                "budget": Decimal("360000.00"),
                "description": "BLE (Bluetooth Low Energy) continuous blood pressure and pulse oximeter monitoring for outpatients.",
                "milestones": [
                    ("BLE Device Firmware SDK Integration", 40, "in_progress"),
                    ("Critical Vitals Threshold Escalation Flow", 0, "pending"),
                ],
                "tasks": [
                    {
                        "title": "Bluetooth Oximeter Data Ingestion Service",
                        "description": "Capture SpO2 and Heart Rate telemetry over secure BLE GATT",
                        "status": "in_progress",
                        "priority": "high",
                        "estimated_hours": Decimal("28.00"),
                        "hours": Decimal("12.00"),
                    },
                    {
                        "title": "Emergency Nurse Call Alert Trigger",
                        "description": "Trigger automated call dispatch if SpO2 drops below 90% for 3 minutes",
                        "status": "todo",
                        "priority": "critical",
                        "estimated_hours": Decimal("20.00"),
                        "hours": Decimal("0.00"),
                    },
                ],
            },
        ],
    },
    "Solaria Energy Corp": {
        "projects": [
            {
                "name": "High-Efficiency Solar Inverter",
                "code": "SOL-INV",
                "client_name": "Adani Green Ventures",
                "status": "active",
                "budget": Decimal("920000.00"),
                "description": "Next-gen bifacial solar inverter hardware firmware pilot with 98.6% peak grid conversion efficiency.",
                "milestones": [
                    ("Thermal Stress Testing Lab Approval", 100, "completed"),
                    ("Firmware MPPT Algorithm v3.2", 80, "in_progress"),
                    ("Field Installation Pilot (500MW Plant)", 30, "pending"),
                ],
                "tasks": [
                    {
                        "title": "MPPT Maximum Power Point Tracker Algorithm",
                        "description": "Optimize rapid irradiance change tracking in overcast conditions",
                        "status": "done",
                        "priority": "critical",
                        "estimated_hours": Decimal("40.00"),
                        "hours": Decimal("40.00"),
                    },
                    {
                        "title": "Inverter Over-Temperature Shutdown Logic",
                        "description": "Calibrate IGBT thermal sensors to protect against desert heat spikes",
                        "status": "in_progress",
                        "priority": "high",
                        "estimated_hours": Decimal("25.00"),
                        "hours": Decimal("18.00"),
                    },
                    {
                        "title": "Modbus RS-485 Communication Protocol",
                        "description": "Implement robust daisy-chained communication for plant SCADA",
                        "status": "review",
                        "priority": "medium",
                        "estimated_hours": Decimal("18.00"),
                        "hours": Decimal("16.00"),
                    },
                    {
                        "title": "Anti-Islanding Safety Disconnect Test",
                        "description": "Ensure inverter disengages under 20ms during grid blackout",
                        "status": "todo",
                        "priority": "critical",
                        "estimated_hours": Decimal("22.00"),
                        "hours": Decimal("0.00"),
                    },
                ],
            },
            {
                "name": "SCADA Solar Grid Telemetry Hub",
                "code": "SCADA-TEL",
                "client_name": "National Power Grid Corp",
                "status": "active",
                "budget": Decimal("620000.00"),
                "description": "Real-time IoT cloud telemetry platform streaming irradiance, panel temperatures, and grid frequency.",
                "milestones": [
                    ("MQTT Broker High-Availability Cluster", 95, "in_progress"),
                    ("Plant Visual Dashboard & String Alarms", 60, "in_progress"),
                ],
                "tasks": [
                    {
                        "title": "TimescaleDB Sensor Ingestion Engine",
                        "description": "Handle 50,000 sensor readings per second with automated compression",
                        "status": "done",
                        "priority": "high",
                        "estimated_hours": Decimal("30.00"),
                        "hours": Decimal("30.00"),
                    },
                    {
                        "title": "String Inverter Fault Detection Classifier",
                        "description": "Detect degraded strings and soiling loss from power curves",
                        "status": "in_progress",
                        "priority": "critical",
                        "estimated_hours": Decimal("32.00"),
                        "hours": Decimal("21.00"),
                    },
                    {
                        "title": "Grafana Plant Overview Dashboards",
                        "description": "Build real-time SVG string diagram overlays for operators",
                        "status": "todo",
                        "priority": "medium",
                        "estimated_hours": Decimal("15.00"),
                        "hours": Decimal("0.00"),
                    },
                ],
            },
            {
                "name": "Bifacial Array Yield Predictor",
                "code": "SOL-PRED",
                "client_name": "Renewable Energy Research",
                "status": "planning",
                "budget": Decimal("340000.00"),
                "description": "Satellite weather forecasting and ground albedo reflection models for accurate 48-hour energy dispatch.",
                "milestones": [
                    ("Satellite Irradiance Data Integration", 50, "in_progress"),
                    ("State Load Dispatch Center (SLDC) Auto Bidding", 0, "pending"),
                ],
                "tasks": [
                    {
                        "title": "MeteoBlue Weather API Downloader",
                        "description": "Download 15-minute global horizontal irradiance forecasts",
                        "status": "in_progress",
                        "priority": "medium",
                        "estimated_hours": Decimal("20.00"),
                        "hours": Decimal("9.00"),
                    },
                    {
                        "title": "Albedo Multiplier Regression Model",
                        "description": "Calculate rear-side bifacial gain according to ground sand type",
                        "status": "todo",
                        "priority": "high",
                        "estimated_hours": Decimal("25.00"),
                        "hours": Decimal("0.00"),
                    },
                ],
            },
        ],
    },
    "Bluepeak Demo Technologies": {
        "projects": [
            {
                "name": "Omni-Channel Customer Portal",
                "code": "BLUE-PORT",
                "client_name": "Horizon Retail Chains",
                "status": "active",
                "budget": Decimal("560000.00"),
                "description": "Modern unified self-service portal for enterprise account ordering, invoice payments, and warranty claims.",
                "milestones": [
                    ("Customer Account Management & RBAC", 100, "completed"),
                    ("Stripe & Wire Payment Gateway", 75, "in_progress"),
                    ("Automated RMA Warranty Ticket Processing", 30, "pending"),
                ],
                "tasks": [
                    {
                        "title": "Role-Based Access Control & Organization Hierarchy",
                        "description": "Enable parent companies to manage multi-store sub accounts",
                        "status": "done",
                        "priority": "critical",
                        "estimated_hours": Decimal("26.00"),
                        "hours": Decimal("26.00"),
                    },
                    {
                        "title": "Instant PDF Invoice & Receipt Generator",
                        "description": "Generate branded high-resolution invoice PDFs on transaction settlement",
                        "status": "in_progress",
                        "priority": "high",
                        "estimated_hours": Decimal("22.00"),
                        "hours": Decimal("14.00"),
                    },
                    {
                        "title": "Zendesk & Freshdesk Bi-directional Ticket Sync",
                        "description": "Keep customer support tickets synchronized across CRM systems",
                        "status": "review",
                        "priority": "medium",
                        "estimated_hours": Decimal("18.00"),
                        "hours": Decimal("17.00"),
                    },
                    {
                        "title": "SSO SAML2 & Okta Integration",
                        "description": "Allow enterprise B2B customers to login via corporate Okta",
                        "status": "todo",
                        "priority": "high",
                        "estimated_hours": Decimal("28.00"),
                        "hours": Decimal("0.00"),
                    },
                ],
            },
            {
                "name": "ERP Supply Chain Connector",
                "code": "ERP-CONN",
                "client_name": "Apex Logistics Network",
                "status": "active",
                "budget": Decimal("480000.00"),
                "description": "SAP NetWeaver and Microsoft Dynamics 365 bidirectional synchronization adapter for inventory and orders.",
                "milestones": [
                    ("SAP RFC & BAPI Connector Service", 80, "in_progress"),
                    ("Real-time Inventory Low-Stock Webhook", 45, "in_progress"),
                ],
                "tasks": [
                    {
                        "title": "SAP Purchase Order Ingestion Flow",
                        "description": "Transform SAP IDoc payloads into standardized JSON format",
                        "status": "done",
                        "priority": "high",
                        "estimated_hours": Decimal("28.00"),
                        "hours": Decimal("28.00"),
                    },
                    {
                        "title": "Warehouse Real-time Stock Sync",
                        "description": "Stream warehouse bin changes to central database every 30 seconds",
                        "status": "in_progress",
                        "priority": "critical",
                        "estimated_hours": Decimal("30.00"),
                        "hours": Decimal("19.00"),
                    },
                    {
                        "title": "Dead-Letter Queue & Reconciliation Alerting",
                        "description": "Notify system admins when ERP payload encounters validation failures",
                        "status": "todo",
                        "priority": "medium",
                        "estimated_hours": Decimal("14.00"),
                        "hours": Decimal("0.00"),
                    },
                ],
            },
            {
                "name": "Enterprise SSO & RBAC Engine",
                "code": "SSO-RBAC",
                "client_name": "Internal Platform Security",
                "status": "planning",
                "budget": Decimal("310000.00"),
                "description": "Zero-trust centralized identity provider supporting OpenID Connect, SAML 2.0, and WebAuthn Passkeys.",
                "milestones": [
                    ("WebAuthn FIDO2 Passwordless Auth", 30, "in_progress"),
                    ("SCIM 2.0 User Provisioning Endpoint", 0, "pending"),
                ],
                "tasks": [
                    {
                        "title": "Hardware FIDO2 Security Key Authenticator",
                        "description": "Implement WebAuthn ceremony with biometric TouchID/YubiKey support",
                        "status": "in_progress",
                        "priority": "high",
                        "estimated_hours": Decimal("26.00"),
                        "hours": Decimal("10.00"),
                    },
                    {
                        "title": "Automated Employee Deprovisioning Hook",
                        "description": "Instantly revoke all active JWT tokens upon employee termination",
                        "status": "todo",
                        "priority": "critical",
                        "estimated_hours": Decimal("18.00"),
                        "hours": Decimal("0.00"),
                    },
                ],
            },
        ],
    },
}

def seed_unique_projects():
    db = SessionLocal()
    bind_tenant_to_session(db, company_id=None, is_platform_admin=True)

    print("🚀 Starting rich unique projects & tasks seeding across all companies...")

    for comp_name, pdata in COMPANIES_DATA.items():
        comp = db.query(Company).filter(Company.name == comp_name).first()
        if not comp:
            print(f"⚠️ Company '{comp_name}' not found, skipping.")
            continue

        employees = db.query(Employee).filter(Employee.company_id == comp.id).all()
        if not employees:
            print(f"⚠️ No employees found for '{comp_name}', skipping.")
            continue

        lead_emp = employees[0]
        print(f"\n🏢 Seeding company: {comp_name} ({comp.id})")

        for proj_info in pdata["projects"]:
            # Check if project exists
            project = db.query(Project).filter(
                Project.company_id == comp.id,
                Project.code == proj_info["code"]
            ).first()

            if not project:
                project = Project(
                    id=uuid.uuid4(),
                    company_id=comp.id,
                    name=proj_info["name"],
                    code=proj_info["code"],
                    client_name=proj_info["client_name"],
                    description=proj_info["description"],
                    status=proj_info["status"],
                    budget=proj_info["budget"],
                    start_date=date.today() - timedelta(days=45),
                    deadline=date.today() + timedelta(days=120),
                    manager_id=lead_emp.id,
                )
                db.add(project)
                db.flush()
                print(f"  + Created Project: [{project.code}] {project.name}")
            else:
                project.name = proj_info["name"]
                project.description = proj_info["description"]
                project.client_name = proj_info["client_name"]
                project.budget = proj_info["budget"]
                project.status = proj_info["status"]
                db.flush()
                print(f"  ✓ Updated Project: [{project.code}] {project.name}")

            # Assign team members (up to 4)
            for emp in employees[:4]:
                pm = db.query(ProjectMember).filter(
                    ProjectMember.company_id == comp.id,
                    ProjectMember.project_id == project.id,
                    ProjectMember.employee_id == emp.id
                ).first()
                if not pm:
                    pm = ProjectMember(
                        id=uuid.uuid4(),
                        company_id=comp.id,
                        project_id=project.id,
                        employee_id=emp.id,
                        role="lead" if emp.id == lead_emp.id else "member",
                        joined_at=date.today() - timedelta(days=30),
                    )
                    db.add(pm)

            # Milestones
            for m_title, m_pct, m_status in proj_info.get("milestones", []):
                ms = db.query(Milestone).filter(
                    Milestone.company_id == comp.id,
                    Milestone.project_id == project.id,
                    Milestone.title == m_title
                ).first()
                if not ms:
                    ms = Milestone(
                        id=uuid.uuid4(),
                        company_id=comp.id,
                        project_id=project.id,
                        title=m_title,
                        status=m_status,
                        completion_percentage=Decimal(str(m_pct)),
                        due_date=date.today() + timedelta(days=30),
                        completed_at=datetime.utcnow() if m_status == "completed" else None,
                    )
                    db.add(ms)

            # Tasks
            for t_idx, t_data in enumerate(proj_info.get("tasks", [])):
                assignee = employees[t_idx % len(employees)]
                task = db.query(Task).filter(
                    Task.company_id == comp.id,
                    Task.project_id == project.id,
                    Task.title == t_data["title"]
                ).first()

                if not task:
                    task = Task(
                        id=uuid.uuid4(),
                        company_id=comp.id,
                        project_id=project.id,
                        title=t_data["title"],
                        description=t_data["description"],
                        status=t_data["status"],
                        priority=t_data["priority"],
                        assigned_to=assignee.id,
                        estimated_hours=t_data["estimated_hours"],
                        due_date=date.today() + timedelta(days=14),
                        completed_at=datetime.utcnow() if t_data["status"] == "done" else None,
                    )
                    db.add(task)
                    db.flush()

                    # Add realistic time entry if hours worked > 0 (each entry <= 8.00 hrs)
                    hrs = t_data.get("hours", Decimal("0.00"))
                    if hrs > Decimal("0.00"):
                        entry_hours = min(hrs, Decimal("8.00"))
                        te = TimeEntry(
                            id=uuid.uuid4(),
                            company_id=comp.id,
                            employee_id=assignee.id,
                            project_id=project.id,
                            task_id=task.id,
                            date=date.today() - timedelta(days=2),
                            hours=entry_hours,
                            description=f"Work on {t_data['title']}: {t_data['description'][:60]}",
                            status="approved",
                            is_billable=True,
                        )
                        db.add(te)

        db.commit()

    print("\n🎉 Seeding complete! All companies now have unique, industry-tailored projects, tasks, milestones, and timesheets.")
    db.close()

if __name__ == "__main__":
    seed_unique_projects()
