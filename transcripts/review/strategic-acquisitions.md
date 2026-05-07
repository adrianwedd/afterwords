# Review: strategic-acquisitions

**Kind:** project  
**Repo:** https://github.com/adrianwedd/strategic-acquisitions  
**URL:** (none)  

---

### A) BLOG POST REVISIONS

CHANGE: "Each step involves a different data source and a different manual process."
TO: "Each step historically involved disparate data sources and manual processing."
REASON: Clarification of the problem state (the project is the solution).

CHANGE: "It fetches listings from the Realty API"
TO: "It fetches listings from the Realty in AU API"
REASON: Accuracy—matching the required environment variable `REALTY_IN_AU_API_BASE_URL`.

CHANGE: "generate GPT-4 analytical insights, runs ML-based property valuations, and scores each opportunity against a multi-factor strategic framework."
TO: "generates GPT-4 analytical insights, runs ML-based property valuations, and scores each opportunity against a multi-factor strategic framework, subsequently creating Jira issues for action."
REASON: Missing detail—the README explicitly mentions creating Jira issues as part of the automated workflow.

CHANGE: "The valuation model trains on engineered features—land per bedroom, bed-bath ratios, latitude-longitude interactions—using cross-validated gradient boosting and random forest estimators."
TO: "The valuation model is served via a Flask API using cross-validated gradient boosting and random forest estimators."
REASON: Correctness—the README clarifies that the Flask app serves the model; the training process is separate from the API functionality described in the architecture.

### B) SYNTHESIS SCRIPT

Housing shortages are rarely just a lack of information. They are a crisis of processing. When a public housing organisation needs to acquire properties, the analysis that should take an hour often stretches into weeks. Listing discovery, valuation modelling, planning zone verification, hazard assessment, and checking infrastructure proximity. Every single one of these steps historically required juggling disparate data sources and manual work.

I built Strategic Acquisitions to automate that entire pipeline. It is an intelligent real estate platform designed specifically for public and social housing organisations. The system handles the heavy lifting, fetching listings via the Realty in AU API, generating deep analytical insights using GPT-4, and scoring each opportunity against a strict multi-factor strategic framework.

The core of the system is a powerful spatial intelligence layer. By integrating directly with Tasmania’s Land Information System, it pulls government-grade data to provide a complete picture of every property. It verifies cadastral title references, checks against planning zones, identifies heritage constraints, and assesses risks like bushfires or floods. It even calculates proximity to schools, public transport, and essential healthcare services. 

All these inputs are funnelled into a scoring model that weights infrastructure access at thirty percent, planning at twenty-five, hazards at twenty, cadastral data at fifteen, and heritage constraints at ten. The result is a clear recommendation—buy, consider, or pass—backed by detailed spatial reasoning.

The technical architecture is built for scale. Listing processing runs asynchronously through Celery, which chains together tasks to ensure data is fetched, analysed, and documented automatically, even creating Jira issues for the team to review. Property valuations are served by a lightweight Flask API, using cross-validated gradient boosting and random forest estimators to provide accurate, data-driven estimates. If a job fails, the system doesn't lose it—it’s moved to a dead letter queue for manual inspection. 

Housing organisations deserve better, more efficient tooling. The data already exists to make smarter, faster decisions for the community. This project simply connects the dots. You can explore the full technical documentation and the architecture diagrams at adrianwedd.com/strategic-acquisitions.
