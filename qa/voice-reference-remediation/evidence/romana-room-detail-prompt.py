from pathlib import Path
import sys
sys.path.insert(0,str(Path('scripts').resolve()))
import listen_voice_corpus as listener
listener.PROMPT += '\nAlso report background_speech_intelligibility, background_relative_level, and background_interference as strings. Listen to the entire WAV. If you hear background chatter, distinguish intelligible words or a material second speaker from indistinct low-level room murmur. State whether it obscures or competes with the foreground voice. Describe whether the first and last words are actually incomplete or merely start/stop without long silence. Do not infer acoustics from a transcript or quote outside speech.\n'
listener.main()
