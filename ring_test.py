from PIL import Image, ImageDraw
import math

# Image settings
width, height = 400, 400
center = (width // 2, height // 2)
outer_radius = 180
ring_step = 20

# Sample data: [accuracy (s), time (hours)]
data = [[10, 6.0], [-20, 12.0], [30, 18.0], [-15, 0.0], [0, 9.0], [40, 15.0], [-50, 21.0], [25, 3.0]]

# Create image
image = Image.new("RGB", (width, height), "white")
draw = ImageDraw.Draw(image)

# Draw 8 rings
for day in range(8):
    radius = outer_radius - (day * ring_step)
    draw.ellipse(
        [center[0] - radius, center[1] - radius, center[0] + radius, center[1] + radius],
        outline="black",
        width=2
    )
    # Accuracy and time
    offset, hour = data[day]
    # Angle: ±60s = ±45°, max ±240s = ±180° around 90° (12 o'clock)
    if abs(offset) <= 60:
        angle_deg = 90 + (offset / 60) * 45
    else:
        angle_deg = 90 + (offset / 240) * 180
    angle_rad = math.radians(angle_deg)
    # Luminance: 128 (6 AM) to 255 (midnight)
    luminance = int(255 - 63.5 * abs(math.sin(math.pi * hour / 12)))
    # Plot point
    x = center[0] + radius * math.cos(angle_rad)
    y = center[1] + radius * math.sin(angle_rad)
    draw.ellipse([x - 5, y - 5, x + 5, y + 5], fill=(luminance, luminance, luminance))

# Clock markers
for hour in range(12):
    angle = math.radians(hour * 30)
    inner_x = center[0] + (outer_radius - 140) * math.cos(angle)
    inner_y = center[1] + (outer_radius - 140) * math.sin(angle)
    outer_x = center[0] + outer_radius * math.cos(angle)
    outer_y = center[1] + outer_radius * math.sin(angle)
    draw.line([inner_x, inner_y, outer_x, outer_y], fill="black", width=2)

# Save
image.save("clock_accuracy.png")
# For hardware (e.g., Raspberry Pi), adapt with display driver
