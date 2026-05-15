from shapely.geometry import Polygon

points = [
    (0, 0),
    (4, 0),
    (4, 1),
    (1, 1),
    (1, 4),
    (0, 4),
]
poly = Polygon(points)
print(poly.area)
