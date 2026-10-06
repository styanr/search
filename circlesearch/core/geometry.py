from dataclasses import dataclass


@dataclass(frozen=True)
class Point:
    x: float
    y: float


@dataclass(frozen=True)
class Rect:
    x: float
    y: float
    w: float
    h: float

    @property
    def right(self):
        return self.x + self.w

    @property
    def bottom(self):
        return self.y + self.h

    @property
    def empty(self):
        return self.w <= 0 or self.h <= 0

    def center(self):
        return Point(self.x + self.w / 2, self.y + self.h / 2)

    def adjusted(self, dx1, dy1, dx2, dy2):
        return Rect(self.x + dx1, self.y + dy1, self.w - dx1 + dx2, self.h - dy1 + dy2)

    def contains(self, other):
        if self.w == 0 or self.h == 0:
            return False
        if isinstance(other, Point):
            return self.x <= other.x <= self.right and self.y <= other.y <= self.bottom
        if other.w == 0 or other.h == 0:
            return False
        return self.x <= other.x and other.right <= self.right and self.y <= other.y and other.bottom <= self.bottom
