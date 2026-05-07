# Review: getting-google-nest-cameras-into-frigate-nvr

**Kind:** blog  
**Repo:** (none)  
**URL:** (none)  

---

### A) BLOG POST REVISIONS

CHANGE: The provided blog post text ends abruptly at `if line.sta`.
TO:
```python
def fix_google_sdp(sdp: str) -> str:
    """Google's SDM SDP has an empty foundation in a=candidate lines.
    Insert a dummy foundation so aiortc's parser can handle it."""
    lines = []
    for line in sdp.splitlines():
        if line.startswith("a=candidate: "):
            # Insert a '0' as a dummy foundation
            lines.append(line.replace("a=candidate: ", "a=candidate:0 "))
        else:
            lines.append(line)
    return "\n".join(lines)
```
REASON: The original content was cut off mid-code block, rendering the solution incomplete.

### B) SYNTHESIS SCRIPT

If you have tried and failed to get Google Nest cameras into Frigate NVR, you are not alone. You have likely hit the same walls I did: the Nest API does not use standard RTSP, and the common trick of using Home Assistant's camera proxy just delivers a low-resolution grayscale placeholder image whenever no one is actively watching the camera.

The actual, programmatic way to do this involves negotiating a direct WebRTC session with Google’s Smart Device Management API. This is not for the faint of heart, but it is the only way to get a continuous, high-quality stream into your local AI object detection pipeline. 

The biggest hurdle is that Google is incredibly strict about how it likes its session negotiation. You must send an SDP offer with three specific media sections in this exact order: audio, then video, and finally an application data channel. If you do not include H264 at 90 kilohertz as a supported codec, the API will simply reject your connection.

Even once you get the handshake right, there is a hidden bug in the ICE candidates Google sends back. The SDP format they provide includes an empty foundation field, which causes standard libraries like aiortc to crash during parsing. You have to manually intercept that SDP answer and patch in a dummy foundation value before your code can successfully decode the video.

Once you have automated this handshake and are piping the stream into Frigate, the result is rock solid. My Raspberry Pi 5 runs YOLOv11 inference on these streams with a 14-millisecond latency, giving me local, private object detection without relying on the cloud. If you want the full code and the exact steps to bypass these API quirks, head over to my site and check out the full guide.
