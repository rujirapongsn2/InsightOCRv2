--
-- PostgreSQL database dump
--

\restrict WSja3kWRwt4Nb81NK5Vhj6sWBMDnsgp7MgS2tbMG4QA7NPebPihIl9iOAS9gOTw

-- Dumped from database version 15.15
-- Dumped by pg_dump version 15.15

SET statement_timeout = 0;
SET lock_timeout = 0;
SET idle_in_transaction_session_timeout = 0;
SET client_encoding = 'UTF8';
SET standard_conforming_strings = on;
SELECT pg_catalog.set_config('search_path', '', false);
SET check_function_bodies = false;
SET xmloption = content;
SET client_min_messages = warning;
SET row_security = off;

--
-- Name: integrationstatus; Type: TYPE; Schema: public; Owner: postgres
--

CREATE TYPE public.integrationstatus AS ENUM (
    'ACTIVE',
    'PAUSED'
);


ALTER TYPE public.integrationstatus OWNER TO postgres;

--
-- Name: integrationtype; Type: TYPE; Schema: public; Owner: postgres
--

CREATE TYPE public.integrationtype AS ENUM (
    'API',
    'WORKFLOW',
    'LLM'
);


ALTER TYPE public.integrationtype OWNER TO postgres;

SET default_tablespace = '';

SET default_table_access_method = heap;

--
-- Name: activity_logs; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.activity_logs (
    id uuid NOT NULL,
    user_id uuid NOT NULL,
    action character varying NOT NULL,
    resource_type character varying,
    resource_id uuid,
    details jsonb,
    ip_address character varying,
    user_agent character varying,
    created_at timestamp with time zone DEFAULT now()
);


ALTER TABLE public.activity_logs OWNER TO postgres;

--
-- Name: ai_settings; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.ai_settings (
    id uuid NOT NULL,
    name character varying NOT NULL,
    display_name character varying NOT NULL,
    api_url character varying NOT NULL,
    api_key character varying NOT NULL,
    is_active boolean,
    is_default boolean,
    description character varying,
    created_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone,
    created_by uuid
);


ALTER TABLE public.ai_settings OWNER TO postgres;

--
-- Name: document_schemas; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.document_schemas (
    id uuid NOT NULL,
    name character varying NOT NULL,
    description character varying,
    document_type character varying NOT NULL,
    ocr_engine character varying,
    fields json,
    template_id uuid,
    created_by uuid,
    created_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone
);


ALTER TABLE public.document_schemas OWNER TO postgres;

--
-- Name: documents; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.documents (
    id uuid NOT NULL,
    job_id uuid NOT NULL,
    filename character varying NOT NULL,
    file_path character varying NOT NULL,
    file_size integer,
    mime_type character varying,
    status character varying,
    ocr_text character varying,
    ocr_confidence double precision,
    page_count integer,
    ocr_pages json,
    processing_error character varying,
    extracted_data json,
    reviewed_data json,
    extraction_confidence double precision,
    uploaded_at timestamp with time zone DEFAULT now(),
    processed_at timestamp with time zone,
    schema_id uuid
);


ALTER TABLE public.documents OWNER TO postgres;

--
-- Name: integrations; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.integrations (
    id uuid NOT NULL,
    user_id uuid NOT NULL,
    name character varying(255) NOT NULL,
    type public.integrationtype NOT NULL,
    description text,
    status public.integrationstatus NOT NULL,
    config jsonb NOT NULL,
    created_at timestamp without time zone NOT NULL,
    updated_at timestamp without time zone NOT NULL
);


ALTER TABLE public.integrations OWNER TO postgres;

--
-- Name: jobs; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.jobs (
    id uuid NOT NULL,
    name character varying,
    description character varying,
    status character varying,
    schema_id uuid,
    user_id uuid,
    created_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone
);


ALTER TABLE public.jobs OWNER TO postgres;

--
-- Name: schema_templates; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.schema_templates (
    id uuid NOT NULL,
    name character varying NOT NULL,
    description character varying,
    document_type character varying NOT NULL,
    category character varying,
    is_system_template boolean NOT NULL,
    thumbnail_url character varying,
    usage_count integer NOT NULL,
    fields json NOT NULL,
    created_by uuid,
    is_active boolean NOT NULL,
    created_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone
);


ALTER TABLE public.schema_templates OWNER TO postgres;

--
-- Name: settings; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.settings (
    id uuid NOT NULL,
    ocr_engine character varying,
    model character varying,
    ocr_endpoint character varying,
    test_endpoint character varying,
    api_endpoint character varying,
    api_token character varying,
    verify_ssl boolean
);


ALTER TABLE public.settings OWNER TO postgres;

--
-- Name: users; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.users (
    id uuid NOT NULL,
    email character varying NOT NULL,
    full_name character varying,
    hashed_password character varying NOT NULL,
    is_active boolean,
    is_superuser boolean,
    role character varying,
    created_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone
);


ALTER TABLE public.users OWNER TO postgres;

--
-- Data for Name: activity_logs; Type: TABLE DATA; Schema: public; Owner: postgres
--

COPY public.activity_logs (id, user_id, action, resource_type, resource_id, details, ip_address, user_agent, created_at) FROM stdin;
7acd3057-4827-49c5-ab1b-e067309417b1	b3bcda6d-7d46-4aec-b9c3-2e8d87daf6b8	login	\N	\N	{"email": "admin@example.com"}	172.66.0.243	Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/26.1 Safari/605.1.15	2025-12-23 08:18:11.034246+00
a219c152-f859-4bb4-9f29-e09bb7f48ff0	b3bcda6d-7d46-4aec-b9c3-2e8d87daf6b8	login	\N	\N	{"email": "admin@example.com"}	172.66.0.243	Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/26.1 Safari/605.1.15	2025-12-23 09:50:57.366249+00
6dfe5bdb-92cd-4618-8c20-912d41d8c5e7	b3bcda6d-7d46-4aec-b9c3-2e8d87daf6b8	update_settings	settings	c5c0d243-97ed-4b79-a23d-bece39c623e0	{"model": "", "ocr_engine": "", "ocr_endpoint": "https://111.223.37.41:9001/ai-process-file", "test_endpoint": "https://111.223.37.41:9001/me"}	\N	\N	2025-12-23 09:51:17.089947+00
8a32e738-723a-486d-b7c0-71c36c27909a	b3bcda6d-7d46-4aec-b9c3-2e8d87daf6b8	create_schema	schema	10a91014-fbae-4934-95bf-2a72c0a14e73	{"schema_name": "Invoicev1", "document_type": "invoice"}	\N	\N	2025-12-23 09:52:46.025535+00
2dc8922b-85a1-4c28-bd90-82d85309db90	b3bcda6d-7d46-4aec-b9c3-2e8d87daf6b8	create_job	job	817dafa3-a5fb-4be9-bc2d-c07985d1e9bd	{"job_name": "Q1"}	\N	\N	2025-12-23 09:52:52.452853+00
1a44e416-051b-4546-9233-d70c3f1cf67f	b3bcda6d-7d46-4aec-b9c3-2e8d87daf6b8	delete_document	document	6eef7914-93ef-4dc9-aaf2-7fe4041908aa	{"filename": "invoice-stripes.pdf"}	\N	\N	2025-12-23 10:09:38.046087+00
53f37f16-ea26-4455-bebf-1e270f42ac96	b3bcda6d-7d46-4aec-b9c3-2e8d87daf6b8	process_document	document	639a8388-7758-441e-abd0-0ed9cbd1da7f	{"filename": "Invoice-INV-1163347-202511-0001.pdf", "job_name": "Q1", "schema_id": "10a91014-fbae-4934-95bf-2a72c0a14e73", "review_status": "pending", "document_status": "extraction_completed", "extraction_status": "completed", "integration_status": null}	\N	\N	2025-12-23 10:17:24.898749+00
c171c244-d18e-4eaa-8c00-a8b1676ccb5f	b3bcda6d-7d46-4aec-b9c3-2e8d87daf6b8	login	\N	\N	{"email": "admin@example.com"}	172.66.0.243	Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/26.1 Safari/605.1.15	2025-12-23 10:27:32.582724+00
8af91ad5-612c-43b5-a21d-efe68f877619	b3bcda6d-7d46-4aec-b9c3-2e8d87daf6b8	change_password	user	b3bcda6d-7d46-4aec-b9c3-2e8d87daf6b8	{"email": "admin@example.com"}	172.66.0.243	Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/26.1 Safari/605.1.15	2025-12-23 10:27:55.934604+00
df12afd0-5c9d-423f-bd05-17ac2a59c1bd	b3bcda6d-7d46-4aec-b9c3-2e8d87daf6b8	login	\N	\N	{"email": "admin@example.com"}	172.66.0.243	Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/26.1 Safari/605.1.15	2025-12-23 10:28:02.924278+00
53ff0098-ef27-4668-a7e3-ad98ccec2148	b3bcda6d-7d46-4aec-b9c3-2e8d87daf6b8	login	\N	\N	{"email": "admin@example.com"}	172.66.0.243	Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/143.0.0.0 Safari/537.36	2025-12-23 10:38:13.953353+00
fa9d5488-974b-46d8-9726-da56b778d56a	b3bcda6d-7d46-4aec-b9c3-2e8d87daf6b8	create_job	job	b83a7f05-6b45-4bbb-83d8-2053daabcd0c	{"job_name": "Q2"}	\N	\N	2025-12-23 10:39:49.1947+00
b21da9ec-0fb4-4b20-a803-befeb0c42ec1	b3bcda6d-7d46-4aec-b9c3-2e8d87daf6b8	process_document	document	5005b0e5-c7ad-42f3-b01a-d6439ed4682a	{"filename": "Invoice-INV-1163347-202511-0001.pdf", "job_name": "Q2", "schema_id": "10a91014-fbae-4934-95bf-2a72c0a14e73", "review_status": "pending", "document_status": "extraction_completed", "extraction_status": "completed", "integration_status": null}	\N	\N	2025-12-23 10:40:23.829351+00
c6a74885-4fb0-4cab-a558-5ee7ddeab1d6	b3bcda6d-7d46-4aec-b9c3-2e8d87daf6b8	login	\N	\N	{"email": "admin@example.com"}	172.66.0.243	Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/143.0.0.0 Safari/537.36	2025-12-23 12:34:05.287446+00
cd8795f5-4542-4c4f-b596-a752cea4777c	b3bcda6d-7d46-4aec-b9c3-2e8d87daf6b8	process_document	document	e0182aa8-ce9b-475b-81e4-e0621be2731d	{"filename": "Invoice-INV-1163347-202511-0001.pdf", "job_name": "Q1", "schema_id": "10a91014-fbae-4934-95bf-2a72c0a14e73", "review_status": "pending", "document_status": "extraction_completed", "extraction_status": "completed", "integration_status": null}	\N	\N	2025-12-23 12:36:42.463932+00
f1fccaca-4cc8-4197-9a14-2d298721fed2	b3bcda6d-7d46-4aec-b9c3-2e8d87daf6b8	process_document	document	f2bd581a-a3d1-4ddf-9f47-131b92bbafb3	{"filename": "Invoice-INV-1163347-202511-0001.pdf", "job_name": "Q1", "schema_id": "10a91014-fbae-4934-95bf-2a72c0a14e73", "review_status": "pending", "document_status": "extraction_completed", "extraction_status": "completed", "integration_status": null}	\N	\N	2025-12-23 12:37:02.326874+00
f8fea7ce-be1e-4ff5-97ea-a2f5b62b6759	b3bcda6d-7d46-4aec-b9c3-2e8d87daf6b8	process_document	document	55a93371-1515-44e1-aaa8-2820a9f10cfa	{"filename": "Invoice-INV-1163347-202511-0001.pdf", "job_name": "Q1", "schema_id": "10a91014-fbae-4934-95bf-2a72c0a14e73", "review_status": "pending", "document_status": "extraction_completed", "extraction_status": "completed", "integration_status": null}	\N	\N	2025-12-23 12:37:06.55796+00
\.


--
-- Data for Name: ai_settings; Type: TABLE DATA; Schema: public; Owner: postgres
--

COPY public.ai_settings (id, name, display_name, api_url, api_key, is_active, is_default, description, created_at, updated_at, created_by) FROM stdin;
f72ceee2-daca-4b9a-9069-6078597ed45c	softnix_genai	Softnix GenAI	https://genai.softnix.ai/external/api/completion-messages	eyJhbGciOiJIUzI1NiJ9.eyJuYW1lIjoib2NyIiwiYXBwX2lkIjoiNjkzMDNiOWM4MTFmN2JiNzIxY2Q3ZDllIiwib3duZXIiOiI2NzE3MzYxYTA5MTMzNWJlODA5NjBlMzAiLCJpYXQiOjE3NjQ3NjkxMjU2NzJ9.IXuWFOM7dhxHly2ypjeMgqiFHByp5UlSB5XkUy3iiP4	t	t	Default Softnix GenAI provider for field suggestions	2025-12-23 08:17:47.91499+00	\N	\N
\.


--
-- Data for Name: document_schemas; Type: TABLE DATA; Schema: public; Owner: postgres
--

COPY public.document_schemas (id, name, description, document_type, ocr_engine, fields, template_id, created_by, created_at, updated_at) FROM stdin;
10a91014-fbae-4934-95bf-2a72c0a14e73	Invoicev1		invoice	tesseract	[{"name": "invoiceNumber", "type": "text", "description": "Invoice number", "required": false, "validation_rules": null}, {"name": "orderDate", "type": "text", "description": "Order date", "required": false, "validation_rules": null}, {"name": "customerName", "type": "text", "description": "Customer's full name", "required": false, "validation_rules": null}, {"name": "address", "type": "text", "description": "Customer's address", "required": false, "validation_rules": null}, {"name": "telephone", "type": "text", "description": "Customer's telephone number", "required": false, "validation_rules": null}, {"name": "shippingMethod", "type": "text", "description": "Shipping method", "required": false, "validation_rules": null}, {"name": "paymentMethod", "type": "text", "description": "Payment method", "required": false, "validation_rules": null}, {"name": "items", "type": "text", "description": "List of purchased items", "required": false, "validation_rules": null}, {"name": "subtotal", "type": "text", "description": "Subtotal amount before discounts and taxes", "required": false, "validation_rules": null}, {"name": "discount", "type": "text", "description": "Discount details", "required": false, "validation_rules": null}, {"name": "tax", "type": "text", "description": "Tax amount", "required": false, "validation_rules": null}, {"name": "shippingAndHandling", "type": "text", "description": "Shipping and handling charges", "required": false, "validation_rules": null}, {"name": "grandTotal", "type": "text", "description": "Total amount to be paid", "required": false, "validation_rules": null}]	\N	b3bcda6d-7d46-4aec-b9c3-2e8d87daf6b8	2025-12-23 09:52:46.013872+00	\N
\.


--
-- Data for Name: documents; Type: TABLE DATA; Schema: public; Owner: postgres
--

COPY public.documents (id, job_id, filename, file_path, file_size, mime_type, status, ocr_text, ocr_confidence, page_count, ocr_pages, processing_error, extracted_data, reviewed_data, extraction_confidence, uploaded_at, processed_at, schema_id) FROM stdin;
f2bd581a-a3d1-4ddf-9f47-131b92bbafb3	817dafa3-a5fb-4be9-bc2d-c07985d1e9bd	Invoice-INV-1163347-202511-0001.pdf	documents/817dafa3-a5fb-4be9-bc2d-c07985d1e9bd/19b77a05-6266-4beb-bfbf-997be2c29bba.pdf	\N	application/pdf	extraction_completed	--- Page 1 Content ---\n## Invoice\n\n**Invoice number:** INV-1163347-202511-0001\n**Date of issue:** November 27, 2025\n**Date due:** November 27, 2025\n\n**From:**\n\nzai\n10 ANSON ROAD, #26-03\nINTERNATIONAL PLAZA, SINGAPORE\nSINGAPORE 079903\nSingapore\nuser_feedback@z.ai\n\n**Bill to:**\n\nRujirapong Ritwong\n153/26 Perfectplace2\nPhatumtani 12000\nThailand\nrujirapong@gmail.com\n\n---\n\n| Description | Qty | Unit price | Amount |\n|---|---|---|---|\n| Subscription (GLM Coding Lite) | 1 | $22.68 | $22.68 |\n\n---\n\n**Subtotal:** $22.68\n**Total:** $22.68\n**Amount due:** $22.68 USD\n\n---\n\nPage 1 of 1\n	\N	1	[{"page_number": 1, "success": true, "content": "## Invoice\\n\\n**Invoice number:** INV-1163347-202511-0001\\n**Date of issue:** November 27, 2025\\n**Date due:** November 27, 2025\\n\\n**From:**\\n\\nzai\\n10 ANSON ROAD, #26-03\\nINTERNATIONAL PLAZA, SINGAPORE\\nSINGAPORE 079903\\nSingapore\\nuser_feedback@z.ai\\n\\n**Bill to:**\\n\\nRujirapong Ritwong\\n153/26 Perfectplace2\\nPhatumtani 12000\\nThailand\\nrujirapong@gmail.com\\n\\n---\\n\\n| Description | Qty | Unit price | Amount |\\n|---|---|---|---|\\n| Subscription (GLM Coding Lite) | 1 | $22.68 | $22.68 |\\n\\n---\\n\\n**Subtotal:** $22.68\\n**Total:** $22.68\\n**Amount due:** $22.68 USD\\n\\n---\\n\\nPage 1 of 1", "confidence": null, "processed_at": "2025-12-23T12:36:37.973016", "error": null}]	\N	{"invoiceNumber": "", "orderDate": "", "customerName": "", "address": "", "telephone": "", "shippingMethod": "", "paymentMethod": "", "items": "Subscription (GLM Coding Lite): 1", "subtotal": "", "discount": "", "tax": "", "shippingAndHandling": "", "grandTotal": ""}	\N	\N	2025-12-23 10:13:57.717814+00	\N	10a91014-fbae-4934-95bf-2a72c0a14e73
55a93371-1515-44e1-aaa8-2820a9f10cfa	817dafa3-a5fb-4be9-bc2d-c07985d1e9bd	Invoice-INV-1163347-202511-0001.pdf	documents/817dafa3-a5fb-4be9-bc2d-c07985d1e9bd/2b6d6316-96b4-41bf-9a46-6f4ecbcd2f3e.pdf	\N	application/pdf	extraction_completed	--- Page 1 Content ---\n## Invoice\n\n**Invoice number:** INV-1163347-202511-0001\n**Date of issue:** November 27, 2025\n**Date due:** November 27, 2025\n\n**From:**\n\nzai\n10 ANSON ROAD, #26-03\nINTERNATIONAL PLAZA, SINGAPORE\nSINGAPORE 079903\nSingapore\nuser_feedback@z.ai\n\n**Bill to:**\n\nRujirapong Ritwong\n153/26 Perfectplace2\nPhatumtani 12000\nThailand\nrujirapong@gmail.com\n\n---\n\n| Description | Qty | Unit price | Amount |\n|---|---|---|---|\n| Subscription (GLM Coding Lite) | 1 | $22.68 | $22.68 |\n\n---\n\n**Subtotal:** $22.68\n**Total:** $22.68\n**Amount due:** $22.68 USD\n\n---\n\nPage 1 of 1\n	\N	1	[{"page_number": 1, "success": true, "content": "## Invoice\\n\\n**Invoice number:** INV-1163347-202511-0001\\n**Date of issue:** November 27, 2025\\n**Date due:** November 27, 2025\\n\\n**From:**\\n\\nzai\\n10 ANSON ROAD, #26-03\\nINTERNATIONAL PLAZA, SINGAPORE\\nSINGAPORE 079903\\nSingapore\\nuser_feedback@z.ai\\n\\n**Bill to:**\\n\\nRujirapong Ritwong\\n153/26 Perfectplace2\\nPhatumtani 12000\\nThailand\\nrujirapong@gmail.com\\n\\n---\\n\\n| Description | Qty | Unit price | Amount |\\n|---|---|---|---|\\n| Subscription (GLM Coding Lite) | 1 | $22.68 | $22.68 |\\n\\n---\\n\\n**Subtotal:** $22.68\\n**Total:** $22.68\\n**Amount due:** $22.68 USD\\n\\n---\\n\\nPage 1 of 1", "confidence": null, "processed_at": "2025-12-23T12:37:02.316195", "error": null}]	\N	{"invoiceNumber": "", "orderDate": "", "customerName": "", "address": "", "telephone": "", "shippingMethod": "", "paymentMethod": "", "items": "Subscription (GLM Coding Lite): 1", "subtotal": "", "discount": "", "tax": "", "shippingAndHandling": "", "grandTotal": ""}	\N	\N	2025-12-23 10:13:28.3512+00	\N	10a91014-fbae-4934-95bf-2a72c0a14e73
639a8388-7758-441e-abd0-0ed9cbd1da7f	817dafa3-a5fb-4be9-bc2d-c07985d1e9bd	Invoice-INV-1163347-202511-0001.pdf	documents/817dafa3-a5fb-4be9-bc2d-c07985d1e9bd/e066c3de-e9b3-4aca-bae1-8d51d9c49c50.pdf	\N	application/pdf	extraction_completed	--- Page 1 Content ---\n## Invoice\n\n**Invoice number:** INV-1163347-202511-0001\n**Date of issue:** November 27, 2025\n**Date due:** November 27, 2025\n\n**From:**\n\nzai\n10 ANSON ROAD, #26-03\nINTERNATIONAL PLAZA, SINGAPORE\nSINGAPORE 079903\nSingapore\nuser_feedback@z.ai\n\n**Bill to:**\n\nRujirapong Ritwong\n153/26 Perfectplace2\nPhatumtani 12000\nThailand\nrujirapong@gmail.com\n\n---\n\n| Description                | Qty | Unit price | Amount |\n|----------------------------|-----|------------|--------|\n| Subscription (GLM Coding Lite) | 1   | $22.68     | $22.68 |\n\n---\n\n**Subtotal:** $22.68\n**Total:** $22.68\n**Amount due:** $22.68 USD\n\n---\n\nPage 1 of 1\n	\N	1	[{"page_number": 1, "success": true, "content": "## Invoice\\n\\n**Invoice number:** INV-1163347-202511-0001\\n**Date of issue:** November 27, 2025\\n**Date due:** November 27, 2025\\n\\n**From:**\\n\\nzai\\n10 ANSON ROAD, #26-03\\nINTERNATIONAL PLAZA, SINGAPORE\\nSINGAPORE 079903\\nSingapore\\nuser_feedback@z.ai\\n\\n**Bill to:**\\n\\nRujirapong Ritwong\\n153/26 Perfectplace2\\nPhatumtani 12000\\nThailand\\nrujirapong@gmail.com\\n\\n---\\n\\n| Description                | Qty | Unit price | Amount |\\n|----------------------------|-----|------------|--------|\\n| Subscription (GLM Coding Lite) | 1   | $22.68     | $22.68 |\\n\\n---\\n\\n**Subtotal:** $22.68\\n**Total:** $22.68\\n**Amount due:** $22.68 USD\\n\\n---\\n\\nPage 1 of 1", "confidence": null, "processed_at": "2025-12-23T10:17:20.503438", "error": null}]	\N	{"invoiceNumber": "", "orderDate": "", "customerName": "", "address": "", "telephone": "", "shippingMethod": "", "paymentMethod": "", "items": "Subscription (GLM Coding Lite): 1", "subtotal": "", "discount": "", "tax": "", "shippingAndHandling": "", "grandTotal": ""}	\N	\N	2025-12-23 10:16:41.677238+00	\N	10a91014-fbae-4934-95bf-2a72c0a14e73
5005b0e5-c7ad-42f3-b01a-d6439ed4682a	b83a7f05-6b45-4bbb-83d8-2053daabcd0c	Invoice-INV-1163347-202511-0001.pdf	documents/b83a7f05-6b45-4bbb-83d8-2053daabcd0c/d100bcbf-a152-4bab-b546-6eb203513c6b.pdf	\N	application/pdf	extraction_completed	--- Page 1 Content ---\n## Invoice\n\n**Invoice number:** INV-1163347-202511-0001\n**Date of issue:** November 27, 2025\n**Date due:** November 27, 2025\n\n**From:**\n\nzai\n10 ANSON ROAD, #26-03\nINTERNATIONAL PLAZA, SINGAPORE\nSINGAPORE 079903\nSingapore\nuser_feedback@z.ai\n\n**Bill to:**\n\nRujirapong Ritwong\n153/26 Perfectplace2\nPhatumtani 12000\nThailand\nrujirapong@gmail.com\n\n---\n\n| Description | Qty | Unit price | Amount |\n|---|---|---|---|\n| Subscription (GLM Coding Lite) | 1 | $22.68 | $22.68 |\n\n---\n\n**Subtotal:** $22.68\n**Total:** $22.68\n**Amount due:** $22.68 USD\n\n---\n\nPage 1 of 1\n	\N	1	[{"page_number": 1, "success": true, "content": "## Invoice\\n\\n**Invoice number:** INV-1163347-202511-0001\\n**Date of issue:** November 27, 2025\\n**Date due:** November 27, 2025\\n\\n**From:**\\n\\nzai\\n10 ANSON ROAD, #26-03\\nINTERNATIONAL PLAZA, SINGAPORE\\nSINGAPORE 079903\\nSingapore\\nuser_feedback@z.ai\\n\\n**Bill to:**\\n\\nRujirapong Ritwong\\n153/26 Perfectplace2\\nPhatumtani 12000\\nThailand\\nrujirapong@gmail.com\\n\\n---\\n\\n| Description | Qty | Unit price | Amount |\\n|---|---|---|---|\\n| Subscription (GLM Coding Lite) | 1 | $22.68 | $22.68 |\\n\\n---\\n\\n**Subtotal:** $22.68\\n**Total:** $22.68\\n**Amount due:** $22.68 USD\\n\\n---\\n\\nPage 1 of 1", "confidence": null, "processed_at": "2025-12-23T10:40:19.986928", "error": null}]	\N	{"invoiceNumber": "", "orderDate": "", "customerName": "", "address": "", "telephone": "", "shippingMethod": "", "paymentMethod": "", "items": "Subscription (GLM Coding Lite): 1", "subtotal": "", "discount": "", "tax": "", "shippingAndHandling": "", "grandTotal": ""}	\N	\N	2025-12-23 10:39:52.506792+00	\N	10a91014-fbae-4934-95bf-2a72c0a14e73
e0182aa8-ce9b-475b-81e4-e0621be2731d	817dafa3-a5fb-4be9-bc2d-c07985d1e9bd	Invoice-INV-1163347-202511-0001.pdf	documents/817dafa3-a5fb-4be9-bc2d-c07985d1e9bd/5db1e57c-b800-4155-939e-fad82cdca7e1.pdf	\N	application/pdf	extraction_completed	--- Page 1 Content ---\n## Invoice\n\n**Invoice number:** INV-1163347-202511-0001\n**Date of issue:** November 27, 2025\n**Date due:** November 27, 2025\n\n**From:**\n\nzai\n10 ANSON ROAD, #26-03\nINTERNATIONAL PLAZA, SINGAPORE\nSINGAPORE 079903\nSingapore\nuser_feedback@z.ai\n\n**Bill to:**\n\nRujirapong Ritwong\n153/26 Perfectplace2\nPhatumtani 12000\nThailand\nrujirapong@gmail.com\n\n---\n\n| Description             | Qty | Unit price | Amount |\n|-------------------------|-----|------------|--------|\n| Subscription (GLM Coding Lite) | 1   | $22.68     | $22.68 |\n\n---\n\n**Subtotal:** $22.68\n**Total:** $22.68\n**Amount due:** $22.68 USD\n\n---\n\nPage 1 of 1\n	\N	1	[{"page_number": 1, "success": true, "content": "## Invoice\\n\\n**Invoice number:** INV-1163347-202511-0001\\n**Date of issue:** November 27, 2025\\n**Date due:** November 27, 2025\\n\\n**From:**\\n\\nzai\\n10 ANSON ROAD, #26-03\\nINTERNATIONAL PLAZA, SINGAPORE\\nSINGAPORE 079903\\nSingapore\\nuser_feedback@z.ai\\n\\n**Bill to:**\\n\\nRujirapong Ritwong\\n153/26 Perfectplace2\\nPhatumtani 12000\\nThailand\\nrujirapong@gmail.com\\n\\n---\\n\\n| Description             | Qty | Unit price | Amount |\\n|-------------------------|-----|------------|--------|\\n| Subscription (GLM Coding Lite) | 1   | $22.68     | $22.68 |\\n\\n---\\n\\n**Subtotal:** $22.68\\n**Total:** $22.68\\n**Amount due:** $22.68 USD\\n\\n---\\n\\nPage 1 of 1", "confidence": null, "processed_at": "2025-12-23T12:36:18.263618", "error": null}]	\N	{"invoiceNumber": "", "orderDate": "", "customerName": "", "address": "", "telephone": "", "shippingMethod": "", "paymentMethod": "", "items": "Subscription (GLM Coding Lite): 1", "subtotal": "", "discount": "", "tax": "", "shippingAndHandling": "", "grandTotal": ""}	\N	\N	2025-12-23 10:09:42.409381+00	\N	10a91014-fbae-4934-95bf-2a72c0a14e73
\.


--
-- Data for Name: integrations; Type: TABLE DATA; Schema: public; Owner: postgres
--

COPY public.integrations (id, user_id, name, type, description, status, config, created_at, updated_at) FROM stdin;
\.


--
-- Data for Name: jobs; Type: TABLE DATA; Schema: public; Owner: postgres
--

COPY public.jobs (id, name, description, status, schema_id, user_id, created_at, updated_at) FROM stdin;
817dafa3-a5fb-4be9-bc2d-c07985d1e9bd	Q1		processing	\N	b3bcda6d-7d46-4aec-b9c3-2e8d87daf6b8	2025-12-23 09:52:52.446392+00	2025-12-23 09:52:57.443018+00
b83a7f05-6b45-4bbb-83d8-2053daabcd0c	Q2		processing	\N	b3bcda6d-7d46-4aec-b9c3-2e8d87daf6b8	2025-12-23 10:39:49.178501+00	2025-12-23 10:39:52.506792+00
\.


--
-- Data for Name: schema_templates; Type: TABLE DATA; Schema: public; Owner: postgres
--

COPY public.schema_templates (id, name, description, document_type, category, is_system_template, thumbnail_url, usage_count, fields, created_by, is_active, created_at, updated_at) FROM stdin;
6f1a06d4-05e6-4ef6-816f-a1d1ada1a678	Standard Invoice	Template for processing standard business invoices with common fields	invoice	financial	t	\N	0	[{"name": "invoice_number", "type": "text", "description": "The unique invoice identifier or number", "required": true, "validation_rules": {}, "help_text": "Unique identifier for this invoice", "example": "INV-2024-001", "order": 1}, {"name": "invoice_date", "type": "date", "description": "The date when the invoice was issued (format: YYYY-MM-DD)", "required": true, "validation_rules": {"format": "YYYY-MM-DD"}, "help_text": "Date the invoice was created", "example": "2024-12-03", "order": 2}, {"name": "due_date", "type": "date", "description": "The payment due date (format: YYYY-MM-DD)", "required": false, "validation_rules": {"format": "YYYY-MM-DD"}, "help_text": "When payment is due", "example": "2024-12-17", "order": 3}, {"name": "vendor_name", "type": "text", "description": "The name of the vendor or supplier", "required": true, "validation_rules": {}, "help_text": "Company or person issuing the invoice", "example": "ABC Corporation", "order": 4}, {"name": "vendor_address", "type": "text", "description": "The vendor's business address", "required": false, "validation_rules": {}, "help_text": "Full address of the vendor", "example": "123 Main St, Bangkok, Thailand", "order": 5}, {"name": "total_amount", "type": "currency", "description": "The total amount including all taxes and fees", "required": true, "validation_rules": {"min": 0}, "help_text": "Final total to be paid", "example": "1,234.56", "order": 6}, {"name": "tax_amount", "type": "currency", "description": "The VAT or tax amount", "required": false, "validation_rules": {"min": 0}, "help_text": "Tax or VAT charged", "example": "123.45", "order": 7}, {"name": "subtotal", "type": "currency", "description": "The subtotal before taxes", "required": false, "validation_rules": {"min": 0}, "help_text": "Amount before tax", "example": "1,111.11", "order": 8}, {"name": "payment_terms", "type": "text", "description": "Payment terms or conditions", "required": false, "validation_rules": {}, "help_text": "Payment conditions (e.g., Net 30)", "example": "Net 30 days", "order": 9}]	\N	t	2025-12-23 08:17:47.912787+00	\N
afc93602-67c7-4ef4-947d-e2bee19b7c9d	Receipt	Template for processing receipts and payment confirmations	receipt	financial	t	\N	0	[{"name": "receipt_number", "type": "text", "description": "The unique receipt identifier or number", "required": true, "validation_rules": {}, "help_text": "Unique receipt ID", "example": "REC-2024-001", "order": 1}, {"name": "date", "type": "date", "description": "The date of purchase or transaction (format: YYYY-MM-DD)", "required": true, "validation_rules": {"format": "YYYY-MM-DD"}, "help_text": "Transaction date", "example": "2024-12-03", "order": 2}, {"name": "merchant_name", "type": "text", "description": "The name of the store or merchant", "required": true, "validation_rules": {}, "help_text": "Store or business name", "example": "ABC Store", "order": 3}, {"name": "merchant_address", "type": "text", "description": "The merchant's business address", "required": false, "validation_rules": {}, "help_text": "Store location", "example": "456 Shopping St, Bangkok", "order": 4}, {"name": "total_amount", "type": "currency", "description": "The total amount paid", "required": true, "validation_rules": {"min": 0}, "help_text": "Total paid", "example": "567.89", "order": 5}, {"name": "payment_method", "type": "text", "description": "The method of payment used (cash, credit card, etc.)", "required": false, "validation_rules": {}, "help_text": "How payment was made", "example": "Credit Card", "order": 6}, {"name": "tax_amount", "type": "currency", "description": "The VAT or tax amount if applicable", "required": false, "validation_rules": {"min": 0}, "help_text": "Tax included in total", "example": "56.78", "order": 7}]	\N	t	2025-12-23 08:17:47.912787+00	\N
cf056451-2bd8-4d94-939e-d97b01440609	Purchase Order	Template for processing purchase orders from procurement	po	procurement	t	\N	0	[{"name": "po_number", "type": "text", "description": "The unique purchase order number", "required": true, "validation_rules": {}, "help_text": "Unique PO identifier", "example": "PO-2024-001", "order": 1}, {"name": "po_date", "type": "date", "description": "The date the purchase order was created (format: YYYY-MM-DD)", "required": true, "validation_rules": {"format": "YYYY-MM-DD"}, "help_text": "PO creation date", "example": "2024-12-03", "order": 2}, {"name": "vendor_name", "type": "text", "description": "The name of the supplier or vendor", "required": true, "validation_rules": {}, "help_text": "Supplier name", "example": "XYZ Supplies Inc", "order": 3}, {"name": "delivery_address", "type": "text", "description": "The address where goods should be delivered", "required": false, "validation_rules": {}, "help_text": "Delivery location", "example": "789 Warehouse Rd, Bangkok", "order": 4}, {"name": "total_amount", "type": "currency", "description": "The total order amount", "required": true, "validation_rules": {"min": 0}, "help_text": "Total PO value", "example": "10,000.00", "order": 5}, {"name": "requested_by", "type": "text", "description": "The name of the person requesting the purchase", "required": false, "validation_rules": {}, "help_text": "Requester name", "example": "John Doe", "order": 6}, {"name": "approved_by", "type": "text", "description": "The name of the person who approved the purchase", "required": false, "validation_rules": {}, "help_text": "Approver name", "example": "Jane Smith", "order": 7}, {"name": "delivery_date", "type": "date", "description": "The requested or expected delivery date (format: YYYY-MM-DD)", "required": false, "validation_rules": {"format": "YYYY-MM-DD"}, "help_text": "When delivery is expected", "example": "2024-12-10", "order": 8}, {"name": "notes", "type": "text", "description": "Any additional notes or special instructions", "required": false, "validation_rules": {}, "help_text": "Special instructions", "example": "Fragile items - handle with care", "order": 9}]	\N	t	2025-12-23 08:17:47.912787+00	\N
8130ccff-eb6c-4460-9109-b3e54df3a583	Contract	Template for processing business contracts and agreements	contract	legal	t	\N	0	[{"name": "contract_number", "type": "text", "description": "The unique contract identifier or reference number", "required": true, "validation_rules": {}, "help_text": "Unique contract ID", "example": "CONT-2024-001", "order": 1}, {"name": "contract_date", "type": "date", "description": "The date when the contract was signed (format: YYYY-MM-DD)", "required": true, "validation_rules": {"format": "YYYY-MM-DD"}, "help_text": "Signing date", "example": "2024-12-03", "order": 2}, {"name": "party_a", "type": "text", "description": "The name of the first party", "required": true, "validation_rules": {}, "help_text": "First contracting party", "example": "ABC Corporation", "order": 3}, {"name": "party_b", "type": "text", "description": "The name of the second party", "required": true, "validation_rules": {}, "help_text": "Second contracting party", "example": "XYZ Company Ltd", "order": 4}, {"name": "start_date", "type": "date", "description": "The contract start date (format: YYYY-MM-DD)", "required": false, "validation_rules": {"format": "YYYY-MM-DD"}, "help_text": "When contract begins", "example": "2024-12-01", "order": 5}, {"name": "end_date", "type": "date", "description": "The contract end or expiration date (format: YYYY-MM-DD)", "required": false, "validation_rules": {"format": "YYYY-MM-DD"}, "help_text": "When contract expires", "example": "2025-11-30", "order": 6}, {"name": "contract_value", "type": "currency", "description": "The total value of the contract", "required": false, "validation_rules": {"min": 0}, "help_text": "Contract monetary value", "example": "50,000.00", "order": 7}, {"name": "terms", "type": "text", "description": "Key terms and conditions of the contract", "required": false, "validation_rules": {}, "help_text": "Main contract terms", "example": "Monthly payments, 30-day notice period", "order": 8}, {"name": "renewal_clause", "type": "text", "description": "Information about contract renewal terms", "required": false, "validation_rules": {}, "help_text": "Renewal conditions", "example": "Auto-renew annually unless terminated", "order": 9}]	\N	t	2025-12-23 08:17:47.912787+00	\N
\.


--
-- Data for Name: settings; Type: TABLE DATA; Schema: public; Owner: postgres
--

COPY public.settings (id, ocr_engine, model, ocr_endpoint, test_endpoint, api_endpoint, api_token, verify_ssl) FROM stdin;
c5c0d243-97ed-4b79-a23d-bece39c623e0			https://111.223.37.41:9001/ai-process-file	https://111.223.37.41:9001/me	https://111.223.37.41:9001/ai-process-file	ocr_ai_key_987654321fedcba	f
\.


--
-- Data for Name: users; Type: TABLE DATA; Schema: public; Owner: postgres
--

COPY public.users (id, email, full_name, hashed_password, is_active, is_superuser, role, created_at, updated_at) FROM stdin;
b3bcda6d-7d46-4aec-b9c3-2e8d87daf6b8	admin@example.com	Initial Admin	$2b$12$9E2tBzxcFmG13XBqJ9Sx6upvzpQngVxnAIr65NJAc0x/pltJPJohy	t	t	admin	2025-12-23 08:17:47.715046+00	2025-12-23 10:27:55.72604+00
\.


--
-- Name: activity_logs activity_logs_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.activity_logs
    ADD CONSTRAINT activity_logs_pkey PRIMARY KEY (id);


--
-- Name: ai_settings ai_settings_name_key; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.ai_settings
    ADD CONSTRAINT ai_settings_name_key UNIQUE (name);


--
-- Name: ai_settings ai_settings_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.ai_settings
    ADD CONSTRAINT ai_settings_pkey PRIMARY KEY (id);


--
-- Name: document_schemas document_schemas_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.document_schemas
    ADD CONSTRAINT document_schemas_pkey PRIMARY KEY (id);


--
-- Name: documents documents_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.documents
    ADD CONSTRAINT documents_pkey PRIMARY KEY (id);


--
-- Name: integrations integrations_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.integrations
    ADD CONSTRAINT integrations_pkey PRIMARY KEY (id);


--
-- Name: jobs jobs_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.jobs
    ADD CONSTRAINT jobs_pkey PRIMARY KEY (id);


--
-- Name: schema_templates schema_templates_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.schema_templates
    ADD CONSTRAINT schema_templates_pkey PRIMARY KEY (id);


--
-- Name: settings settings_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.settings
    ADD CONSTRAINT settings_pkey PRIMARY KEY (id);


--
-- Name: users users_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.users
    ADD CONSTRAINT users_pkey PRIMARY KEY (id);


--
-- Name: ix_activity_logs_action; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX ix_activity_logs_action ON public.activity_logs USING btree (action);


--
-- Name: ix_activity_logs_created_at; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX ix_activity_logs_created_at ON public.activity_logs USING btree (created_at);


--
-- Name: ix_activity_logs_id; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX ix_activity_logs_id ON public.activity_logs USING btree (id);


--
-- Name: ix_activity_logs_user_id; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX ix_activity_logs_user_id ON public.activity_logs USING btree (user_id);


--
-- Name: ix_document_schemas_id; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX ix_document_schemas_id ON public.document_schemas USING btree (id);


--
-- Name: ix_document_schemas_name; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX ix_document_schemas_name ON public.document_schemas USING btree (name);


--
-- Name: ix_documents_id; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX ix_documents_id ON public.documents USING btree (id);


--
-- Name: ix_jobs_id; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX ix_jobs_id ON public.jobs USING btree (id);


--
-- Name: ix_schema_templates_id; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX ix_schema_templates_id ON public.schema_templates USING btree (id);


--
-- Name: ix_schema_templates_name; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX ix_schema_templates_name ON public.schema_templates USING btree (name);


--
-- Name: ix_settings_id; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX ix_settings_id ON public.settings USING btree (id);


--
-- Name: ix_users_email; Type: INDEX; Schema: public; Owner: postgres
--

CREATE UNIQUE INDEX ix_users_email ON public.users USING btree (email);


--
-- Name: ix_users_full_name; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX ix_users_full_name ON public.users USING btree (full_name);


--
-- Name: ix_users_id; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX ix_users_id ON public.users USING btree (id);


--
-- Name: activity_logs activity_logs_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.activity_logs
    ADD CONSTRAINT activity_logs_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id);


--
-- Name: document_schemas document_schemas_created_by_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.document_schemas
    ADD CONSTRAINT document_schemas_created_by_fkey FOREIGN KEY (created_by) REFERENCES public.users(id);


--
-- Name: document_schemas document_schemas_template_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.document_schemas
    ADD CONSTRAINT document_schemas_template_id_fkey FOREIGN KEY (template_id) REFERENCES public.schema_templates(id);


--
-- Name: documents documents_job_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.documents
    ADD CONSTRAINT documents_job_id_fkey FOREIGN KEY (job_id) REFERENCES public.jobs(id);


--
-- Name: documents documents_schema_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.documents
    ADD CONSTRAINT documents_schema_id_fkey FOREIGN KEY (schema_id) REFERENCES public.document_schemas(id);


--
-- Name: integrations integrations_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.integrations
    ADD CONSTRAINT integrations_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id);


--
-- Name: jobs jobs_schema_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.jobs
    ADD CONSTRAINT jobs_schema_id_fkey FOREIGN KEY (schema_id) REFERENCES public.document_schemas(id);


--
-- Name: jobs jobs_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.jobs
    ADD CONSTRAINT jobs_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id);


--
-- Name: schema_templates schema_templates_created_by_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.schema_templates
    ADD CONSTRAINT schema_templates_created_by_fkey FOREIGN KEY (created_by) REFERENCES public.users(id);


--
-- PostgreSQL database dump complete
--

\unrestrict WSja3kWRwt4Nb81NK5Vhj6sWBMDnsgp7MgS2tbMG4QA7NPebPihIl9iOAS9gOTw

