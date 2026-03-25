from mss import mss

with mss() as sct:
    filename = sct.shot(output='screenshot.png')
    print('Screenshot saved to', filename)
