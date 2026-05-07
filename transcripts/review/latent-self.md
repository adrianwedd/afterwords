# Review: latent-self

**Kind:** project  
**Repo:** https://github.com/adrianwedd/latent-self  
**URL:** (none)  

---

### A) BLOG POST REVISIONS

CHANGE: "Six emotion presets map to directions in latent space, each one a vector away from the face you walked in with."
TO: "Multiple transformation axes (age, gender, smile, species, beauty) and six emotion presets allow you to shift your image along vectors in latent space."
REASON: Accuracy; the original text missed the core axes (age, gender, etc.) mentioned in the repo features and focused too heavily on emotions.

CHANGE: "MQTT heartbeat for remote monitoring."
TO: "MQTT heartbeat for remote monitoring, and a lightweight web-based admin API for managing configuration over the local network."
REASON: Missing detail; the README highlights the web-based remote admin capability which is a significant feature.

---

### B) SYNTHESIS SCRIPT

A traditional mirror shows you what you are, providing a direct reflection of your presence. Latent Self is an interactive art installation that pushes past that simple reflection to show you what you almost are. 

When you stand in front of the mirror, it uses a camera to capture your face and processes it through a StyleGAN2 model in real-time. By navigating through latent space, the installation shifts your features along specific axes—like age, gender, smile, or even species—and lets you cycle through six different emotional presets. 

While we have become accustomed to spotting the seams in static deepfakes, the experience here is different because it is continuous and responsive. Because the system tracks your face and morphs it in real-time, it sits in that productive gap between recognition and estrangement, the same strange place that makes traditional mirrors so compelling. 

Technically, the installation is built for flexibility. You can run it in a full-screen kiosk mode for gallery settings, manage configurations remotely through an integrated web API, or monitor the system's health via an MQTT heartbeat. The infrastructure is designed to be invisible so that the technology disappears and you are left only with the reflection of your own possibility. 

If you want to try building your own version or explore the source, you can find the complete project, including the model requirements and setup guides, at the link below.

https://github.com/adrianwedd/latent-self
