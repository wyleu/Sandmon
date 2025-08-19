from PIL import Image, ImageDraw
import math
import random

# Image settings
width, height = 400, 400
center = (width // 2, height // 2)
outer_radius = 180
ring_step = 3  # Points (radius 3) touch next ring position

# Rainbow colors (day 0 to 7)
colors = [
    (255, 0, 0), (255, 165, 0), (255, 255, 0), (0, 255, 0),
    (0, 255, 255), (0, 0, 255), (75, 0, 130), (238, 130, 238)
]

# Generate data: 20 points/day, 8 days
data = []
for day in range(8):
    for i in range(20):
        t = i * 1.2  # Every 1.2 hours
        # Random accuracy: ±60s normal, ±240s outliers (5% chance)
        if random.random() < 0.05:  # Outlier
            offset = random.uniform(-240, -60) if random.random() < 0.5 else random.uniform(60, 240)
        else:  # Normal
            offset = random.uniform(-60, 60)
        offset += 10  # Apply 10-second offset
        offset = min(max(offset, -240), 240)  # Clamp to ±240s
        data.append([offset, t])

# Create image
image = Image.new("RGB", (width, height), "black")
draw = ImageDraw.Draw(image)

# Plot points (no ring outlines)
for day in range(8):
    radius = outer_radius - (day * ring_step)
    for i in range(20):
        idx = day * 20 + i
        offset, hour = data[idx]
        # Angle: ±60s = ±45°, max ±240s = ±180° around 90°
        if abs(offset) <= 60:
            angle_deg = 90 + (offset / 60) * 45
        else:
            angle_deg = 90 + (offset / 240) * 180
        angle_rad = math.radians(angle_deg)
        # Luminance: 128 (6 AM) to 255 (midnight)
        luminance = 255 - 63.5 * abs(math.sin(math.pi * hour / 12))
        # Scale color
        color = colors[day]
        scaled_color = tuple(int(c * luminance / 255) for c in color)
        # Plot point
        x = center[0] + radius * math.cos(angle_rad)
        y = center[1] + radius * math.sin(angle_rad)
        draw.ellipse([x - 3, y - 3, x + 3, y + 3], fill=scaled_color)

# Save and display
image.save("ring_test.png")
image.show()
