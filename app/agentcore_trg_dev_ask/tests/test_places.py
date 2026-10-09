"""Tests for the place tools.

Amazon Location is stubbed: these pin the parts the model must not do itself -
reading the position from the payload rather than from its own arguments, and
working out distance, direction and side - plus the failures that must leave the
model able to answer.
"""

from types import SimpleNamespace

import pytest

from tools import places

TOKYO_STATION = {"latitude": 35.6812, "longitude": 139.7671}


def _context(location=None) -> SimpleNamespace:
    state = {} if location is None else {places.LOCATION_KEY: location}
    return SimpleNamespace(invocation_state=state)


def _place(title: str, lat: float, lon: float, distance: int = 0) -> dict:
    # The API's Position is [longitude, latitude].
    return {"Title": title, "Position": [lon, lat], "Distance": distance}


class _Client:
    def __init__(self, items=None, error=None):
        self.items = items or []
        self.error = error
        self.calls: list[tuple[str, dict]] = []

    def _reply(self, name: str, kwargs: dict) -> dict:
        self.calls.append((name, kwargs))
        if self.error is not None:
            raise self.error
        return {"ResultItems": self.items}

    def search_nearby(self, **kwargs):
        return self._reply("search_nearby", kwargs)

    def search_text(self, **kwargs):
        return self._reply("search_text", kwargs)


@pytest.fixture
def client(monkeypatch):
    stub = _Client()
    monkeypatch.setattr(places, "_client", stub)
    return stub


# --- geometry ---------------------------------------------------------------


@pytest.mark.parametrize(
    "bearing, heading, expected",
    [
        (0, 0, "前方"),
        (45, 0, "右前方"),
        (90, 0, "右手"),
        (135, 0, "右後方"),
        (180, 0, "後方"),
        (225, 0, "左後方"),
        (270, 0, "左手"),
        (315, 0, "左前方"),
        # Wraps around north: heading 350, place at 80 is to the right.
        (80, 350, "右手"),
        (260, 350, "左手"),
        (10, 350, "前方"),
        # Fuji from Chiba heading east: west-south-west is behind on the right.
        (247, 90, "右後方"),
    ],
)
def test_side_of(bearing, heading, expected):
    assert places.side_of(bearing, heading) == expected


def test_bearing_points_the_right_way():
    # A point due north and one due east of Tokyo Station.
    lat, lon = TOKYO_STATION["latitude"], TOKYO_STATION["longitude"]
    assert places.bearing_degrees(lat, lon, lat + 0.01, lon) == pytest.approx(0, abs=0.5)
    assert places.bearing_degrees(lat, lon, lat, lon + 0.01) == pytest.approx(90, abs=0.5)


@pytest.mark.parametrize(
    "meters, expected",
    [(3, "約10m"), (154, "約150m"), (999, "約1000m"), (1957, "約2.0km"), (12755, "約12.8km")],
)
def test_format_distance(meters, expected):
    assert places.format_distance(meters) == expected


# --- reading the position -----------------------------------------------------


@pytest.mark.parametrize(
    "state",
    [
        None,
        {},
        {"location": None},
        {"location": "35.68,139.76"},
        {"location": {"latitude": "35.68", "longitude": 139.76}},
        {"location": {"latitude": True, "longitude": 139.76}},
    ],
)
def test_unusable_location_is_none(state):
    assert places.read_location(state) is None


def test_heading_is_optional():
    location = places.read_location({"location": dict(TOKYO_STATION)})
    assert location == {**TOKYO_STATION, "heading": None}


# --- search_nearby_places -----------------------------------------------------


def test_nearby_uses_the_payload_position_longitude_first(client):
    places.search_nearby_places(kind="公園", tool_context=_context(TOKYO_STATION))

    name, kwargs = client.calls[0]
    assert name == "search_nearby"
    assert kwargs["QueryPosition"] == [139.7671, 35.6812]
    assert kwargs["Filter"] == {"IncludeCategories": ["park-recreation_area", "garden"]}
    assert kwargs["Language"] == "ja"


def test_nearby_states_side_direction_and_distance(client):
    lat, lon = TOKYO_STATION["latitude"], TOKYO_STATION["longitude"]
    client.items = [_place("東の公園", lat, lon + 0.01)]
    heading_north = {**TOKYO_STATION, "headingDegrees": 0}

    answer = places.search_nearby_places(kind="公園", tool_context=_context(heading_north))

    assert "東の公園（右手・東の方角 約900m）" in answer


def test_side_filter_keeps_only_that_side(client):
    lat, lon = TOKYO_STATION["latitude"], TOKYO_STATION["longitude"]
    client.items = [
        _place("西の公園", lat, lon - 0.005),
        _place("東の公園", lat, lon + 0.01),
    ]
    heading_north = {**TOKYO_STATION, "headingDegrees": 0}

    answer = places.search_nearby_places(
        kind="公園", side="右手", tool_context=_context(heading_north)
    )

    assert "東の公園" in answer
    assert "西の公園" not in answer


def test_side_filter_includes_the_diagonals(client):
    # Ahead-right is still "on the right" when the rider asks for the right.
    lat, lon = TOKYO_STATION["latitude"], TOKYO_STATION["longitude"]
    client.items = [_place("右前の公園", lat + 0.007, lon + 0.007)]
    heading_north = {**TOKYO_STATION, "headingDegrees": 0}

    answer = places.search_nearby_places(
        kind="公園", side="右手", tool_context=_context(heading_north)
    )

    assert "右前の公園（右前方・" in answer


def test_no_side_is_given_without_a_heading(client):
    lat, lon = TOKYO_STATION["latitude"], TOKYO_STATION["longitude"]
    client.items = [_place("東の公園", lat, lon + 0.01)]

    answer = places.search_nearby_places(kind="公園", tool_context=_context(TOKYO_STATION))

    assert "東の公園（東の方角 約900m）" in answer
    assert "右手" not in answer
    assert "左右は付けていません" in answer


def test_side_filter_without_a_heading_says_why(client):
    client.items = [_place("東の公園", 35.6812, 139.78)]

    answer = places.search_nearby_places(
        kind="公園", side="右手", tool_context=_context(TOKYO_STATION)
    )

    assert "進行方向が分からない" in answer


def test_duplicates_are_listed_once(client):
    client.items = [_place("皇居外苑", 35.68, 139.76), _place("皇居外苑", 35.68, 139.76)]

    answer = places.search_nearby_places(kind="公園", tool_context=_context(TOKYO_STATION))

    assert answer.count("皇居外苑") == 1


def test_at_most_a_few_places_are_returned(client):
    client.items = [_place(f"公園{i}", 35.68 + i * 0.001, 139.76) for i in range(10)]

    answer = places.search_nearby_places(kind="公園", tool_context=_context(TOKYO_STATION))

    assert answer.count("\n- ") == places.MAX_RETURNED


def test_radius_is_clamped(client):
    places.search_nearby_places(kind="山・自然", radius_km=500, tool_context=_context(TOKYO_STATION))

    assert client.calls[0][1]["QueryRadius"] == int(places.MAX_RADIUS_KM * 1000)


def test_every_kind_has_categories():
    assert set(places.KINDS) == set(places.Kind.__args__)


# --- search_places_by_name ----------------------------------------------------


def test_by_name_is_biased_to_the_rider_and_sorted_by_distance(client):
    client.items = [
        _place("マクドナルド 遠い店", 35.70, 139.7671, distance=2000),
        _place("マクドナルド 近い店", 35.682, 139.7671, distance=100),
    ]

    answer = places.search_places_by_name(name="マクドナルド", tool_context=_context(TOKYO_STATION))

    _, kwargs = client.calls[0]
    assert kwargs["BiasPosition"] == [139.7671, 35.6812]
    assert kwargs["QueryText"] == "マクドナルド"
    assert answer.index("近い店") < answer.index("遠い店")


# --- failures ---------------------------------------------------------------


def test_no_location_means_no_search(client):
    answer = places.search_places_by_name(name="マクドナルド", tool_context=_context())

    assert answer == places._NO_LOCATION
    assert client.calls == []


def test_aws_error_is_a_sentence_not_an_exception(client):
    client.error = RuntimeError("AccessDeniedException")

    answer = places.search_nearby_places(kind="公園", tool_context=_context(TOKYO_STATION))

    assert answer == places._FAILED


def test_nothing_found(client):
    answer = places.search_places_by_name(name="存在しない店", tool_context=_context(TOKYO_STATION))

    assert "見つかりませんでした" in answer
