# Review: cygnet

**Kind:** project  
**Repo:** https://github.com/adrianwedd/cygnet  
**URL:** (none)  

---

### A) BLOG POST REVISIONS

CHANGE: "twenty-eight specialised AI agents coordinating land acquisition, building operations, and print logistics across what is designed to become an eco village."
TO: "a geospatial research tool that connects to Tasmania’s LISTmap services to analyze and visualize land parcel data for housing research."
REASON: The project is a geospatial data viewer, not an AI agent system for housing development.

CHANGE: "The goal is sixty percent cost reduction against traditional construction, eighty percent waste reduction, and a carbon footprint halved—not as aspiration, but as engineering constraint."
TO: "The goal is to provide a robust, interactive platform for evaluating land potential and geospatial constraints, moving beyond static spreadsheets toward data-driven analysis."
REASON: This is an aspiration/hallucination not supported by the technical implementation in the repository.

CHANGE: "When housing is broken at the system level, you don't fix it by building the same thing slightly cheaper. You rethink what building means."
TO: "Understanding land potential requires better tools for geospatial analysis. You start by visualizing the data."
REASON: The original text promotes a project scope that does not exist in the source code.

---

### B) SYNTHESIS SCRIPT

You are looking at Cygnet, a research tool built to improve how we approach housing development in Tasmania. When you look at the economics and logistics of large-scale construction, it is clear that the industry's existing incentive structures often fall short.

Cygnet provides a different path, starting with data. It is a geospatial viewer that bridges the gap between raw public data and actionable planning. By connecting directly to Tasmania's official LISTmap services, the platform allows you to pull in complex WFS and WMS data, making it possible to visualize land parcel information in an interactive, web-based dashboard.

The problem with conventional housing research is often found in the tooling. Data is siloed, hard to access, and even harder to visualize alongside other variables. Cygnet solves this by centralizing that geospatial information, letting you query, cache, and display the layers that matter for site assessment. Under the hood, it uses a FastAPI backend to handle the heavy lifting of spatial queries, while the frontend is built on React and Leaflet to provide a responsive, performant map interface.

This is not about replacing human decision-making with automated agents. It is about accelerating the parts of the research process that are slow because of poor tooling—like managing complex geospatial datasets and simplifying GeoJSON for better performance. By building tools that make land parcel data accessible and easy to analyze, we can make more informed decisions about future development.

If you are interested in geospatial research or want to see how these data services are integrated, you can find the project and the technical documentation at the link below.
