# Review: space-weather

**Kind:** project  
**Repo:** https://github.com/adrianwedd/space-weather  
**URL:** (none)  

---

### A) BLOG POST REVISIONS

CHANGE: `repo: 'https://github.com/adrianwedd/space-weather'`
TO: `repo: 'https://github.com/adrianwedd/space-weather'` (Note: Verify the repo existence/access if possible, but keep as is if correct).
REASON: The post is generally accurate. The content focuses on the purpose of the dashboard, while the repository provides the technical implementation details. No content errors identified in the provided markdown.

POST OK

---

### B) SYNTHESIS SCRIPT

The sun is a noisy neighbour. Coronal mass ejections, solar wind variations, and geomagnetic storms are not just abstract concepts from an astrophysics textbook. They have real-world consequences, affecting radio propagation, satellite operations, and even the power grids we rely on every single day. If you have ever wondered why your GPS was slightly off on a particular afternoon, you might be looking at the invisible weather happening far above us.

The Australian Bureau of Meteorology publishes space weather data, but their raw feeds are not exactly designed for casual monitoring. That is where this project comes in. I built a modern dashboard to pull real-time A-Index, K-Index, and Dst-Index data and present it in a clean, readable interface. It is built using a FastAPI backend to proxy the data, paired with a React and TypeScript frontend styled with Tailwind CSS.

This dashboard makes the invisible visible, turning complex cosmic data into a simple window into the weather that does not care if you are watching. It is about understanding the electromagnetic environment that shapes the reliability of the infrastructure we depend on. You can check out the source code and start running your own instance of the dashboard over at my GitHub repository.
