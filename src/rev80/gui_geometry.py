"""Window geometry from proportional bounds. No dearpygui import."""

Bounds = tuple[float, float]


def _check_bounds(name: str, bounds: Bounds) -> None:
    lo, hi = bounds
    if not 0.0 <= lo < hi <= 1.0:
        raise ValueError(f'{name} bounds must be 0 <= low < high <= 1, not {bounds}')


def proportional_rect(client_w: int, client_h: int,
                      bounds_x: Bounds, bounds_y: Bounds) -> tuple[int, int, int, int]:
    """(x, y, width, height) in pixels of the area between proportional bounds.

    `bounds_x` and `bounds_y` are (low, high) fractions of the client width
    and height. Each edge is rounded to a whole pixel, so the far edges are
    at round(high x size).
    """
    if client_w <= 0 or client_h <= 0:
        raise ValueError(f'client area must have a size, not {client_w} x {client_h}')
    _check_bounds('x', bounds_x)
    _check_bounds('y', bounds_y)
    left, right = (round(f * client_w) for f in bounds_x)
    top, bottom = (round(f * client_h) for f in bounds_y)
    return left, top, right - left, bottom - top
