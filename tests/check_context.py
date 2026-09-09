import sys
sys.path.insert(0, '.')
from app import storage

session = storage.get_session('testuser', '85996783c63448f19da6b0566378d716')
transcript = session['transcript']
chars = sum(len(item.get('text', '')) for item in transcript)
print(f'Transcript: {len(transcript)} items, {chars} chars')
print(f'Threshold: 12800 chars')
print(f'Status: {"READY FOR AUTO-COMPRESS" if chars > 12800 else "NEAR THRESHOLD"}')
print(f'\nLogin: testuser / test123')
print(f'Open: http://localhost:8000')
