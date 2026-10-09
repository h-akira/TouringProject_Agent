"""Places around the rider, via Amazon Location Service (geo-places).

Answers "what is that park on my right?" and "where is the nearest
McDonald's?". The prompt only says which town the rider is in; the model
cannot place anything finer than that from coordinates (it once named a city
about 40km away), and it is told not to work out directions itself.

So these tools do the geometry in code and hand the model a finished answer:
name, distance, compass direction and which side of the rider it is on. Two
rules keep that honest:

  - The position and heading come from the payload the Backend sends, via
    Strands' invocation_state - never from the model's own arguments. Copying
    coordinates is exactly what the model gets wrong.
  - A failed lookup returns a sentence, not an exception, so the model can
    still answer (or say it does not know) instead of the question failing.

Measurements behind the category IDs and the caveats:
https://github.com/h-akira/TouringProject_Research/blob/main/geocoding/FINDINGS.md
"""

import math
import os
from typing import Any, Literal, Optional

import boto3
from strands import ToolContext, tool

# Same region as the runtime, so no cross-region hop. The places data is the
# same as from Tokyo (checked for both search calls).
PLACES_REGION = os.environ.get("PLACES_REGION", "us-east-1")

# Key in invocation_state that main.py fills from the payload's `location`.
LOCATION_KEY = "location"

# What the model may ask for, mapped to Amazon Location category IDs. The
# labels are what the model sees, so they are the words a rider would use.
# IDs are case-sensitive and must be IDs, not display names (a display name is
# a ValidationException). "park" does not exist; parks are split between
# park-recreation_area and garden (日比谷公園 is a garden).
KINDS: dict[str, list[str]] = {
    "公園": ["park-recreation_area", "garden"],
    "山・自然": ["natural_and_geographical", "mountain_or_hill"],
    "観光地": ["tourist_attraction"],
    "景色のよい場所": ["scenic_point"],
    "神社・寺": ["shrine", "temple"],
    "温泉": ["hot_spring"],
    "ガソリンスタンド": ["petrol-gasoline_station"],
    "EV充電": ["ev_charging_station"],
    "コンビニ": ["convenience_store"],
    "道の駅・休憩所": [
        "roadside_station",
        "rest_area",
        "parking_and_restroom_only_rest_area",
    ],
    "トイレ": ["public_restroom-toilets"],
    "駐車場": ["parking"],
    "カフェ": ["coffee_shop"],
    "飲食店": ["restaurant", "casual_dining", "family_restaurant", "fast_food"],
    "病院": ["hospital"],
}

Kind = Literal[
    "公園",
    "山・自然",
    "観光地",
    "景色のよい場所",
    "神社・寺",
    "温泉",
    "ガソリンスタンド",
    "EV充電",
    "コンビニ",
    "道の駅・休憩所",
    "トイレ",
    "駐車場",
    "カフェ",
    "飲食店",
    "病院",
]
Side = Literal["右手", "左手", "前方", "後方"]

# Eight sectors of 45 degrees, clockwise from straight ahead. Finer than the
# four sides the model may filter by, so it never has to refine "behind" into
# "behind on the right" by itself.
_SECTORS = ("前方", "右前方", "右手", "右後方", "後方", "左後方", "左手", "左前方")

# Which sectors count as each side the model can ask for. Diagonals belong to
# both neighbours: a park ahead on the right is "on the right" and "ahead".
_SIDE_SECTORS: dict[str, set[str]] = {
    "右手": {"右前方", "右手", "右後方"},
    "左手": {"左前方", "左手", "左後方"},
    "前方": {"左前方", "前方", "右前方"},
    "後方": {"左後方", "後方", "右後方"},
}

# How many places to hand back. Read aloud, more than a few is noise.
MAX_RETURNED = 5
# How many to fetch when filtering by side, so a filter still leaves some.
MAX_FETCHED = 20

MIN_RADIUS_KM = 0.2
MAX_RADIUS_KM = 50.0

_COMPASS_POINTS = (
    "北", "北北東", "北東", "東北東", "東", "東南東", "南東", "南南東",
    "南", "南南西", "南西", "西南西", "西", "西北西", "北西", "北北西",
)

_client = None


def _get_client() -> Any:
    """Build the client lazily so importing this module needs no credentials."""
    global _client
    if _client is None:
        _client = boto3.client("geo-places", region_name=PLACES_REGION)
    return _client


def bearing_degrees(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Initial great-circle bearing from point 1 to point 2, clockwise from north."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dl = math.radians(lon2 - lon1)
    x = math.sin(dl) * math.cos(p2)
    y = math.cos(p1) * math.sin(p2) - math.sin(p1) * math.cos(p2) * math.cos(dl)
    return math.degrees(math.atan2(x, y)) % 360


def compass(bearing: float) -> str:
    """16-point compass name for a bearing."""
    return _COMPASS_POINTS[int((bearing % 360) / 22.5 + 0.5) % 16]


def side_of(bearing: float, heading: float) -> str:
    """Where a bearing lies for a rider travelling along `heading`.

    One of eight 45-degree sectors (_SECTORS), e.g. 右後方 for behind-right.
    """
    relative = (bearing - heading) % 360
    return _SECTORS[int(relative / 45 + 0.5) % 8]


def format_distance(meters: float) -> str:
    """Distance as it should be read aloud."""
    if meters < 1000:
        return f"約{max(10, round(meters, -1)):.0f}m"
    return f"約{meters / 1000:.1f}km"


def read_location(invocation_state: Optional[dict]) -> Optional[dict]:
    """The rider's position and heading from the payload, or None if unusable."""
    location = (invocation_state or {}).get(LOCATION_KEY)
    if not isinstance(location, dict):
        return None
    lat, lon = location.get("latitude"), location.get("longitude")
    if not isinstance(lat, (int, float)) or not isinstance(lon, (int, float)):
        return None
    if isinstance(lat, bool) or isinstance(lon, bool):
        return None
    heading = location.get("headingDegrees")
    if not isinstance(heading, (int, float)) or isinstance(heading, bool):
        heading = None
    return {"latitude": float(lat), "longitude": float(lon), "heading": heading}


def describe_places(
    items: list[dict], location: dict, side: Optional[Side] = None
) -> list[str]:
    """Turn API results into lines the model can read out as fact.

    Distance and direction are recomputed from each result's Position rather
    than taken from the API, so the side and the distance always agree.
    """
    lat, lon, heading = location["latitude"], location["longitude"], location["heading"]
    lines: list[str] = []
    seen: set[str] = set()
    for item in items:
        title = item.get("Title")
        position = item.get("Position")
        if not title or not isinstance(position, list) or len(position) != 2:
            continue
        if title in seen:
            # The same place is often listed twice (two entrances, two shops).
            continue
        # Position is [longitude, latitude].
        place_lon, place_lat = position
        bearing = bearing_degrees(lat, lon, place_lat, place_lon)
        meters = _distance_meters(lat, lon, place_lat, place_lon)

        place_side = side_of(bearing, heading) if heading is not None else None
        if side is not None and place_side not in _SIDE_SECTORS[side]:
            continue

        seen.add(title)
        where = f"{compass(bearing)}の方角 {format_distance(meters)}"
        if place_side is not None:
            where = f"{place_side}・{where}"
        lines.append(f"{title}（{where}）")
        if len(lines) >= MAX_RETURNED:
            break
    return lines


def _distance_meters(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * 6_371_000 * math.asin(math.sqrt(a))


def _answer(lines: list[str], location: dict, side: Optional[Side]) -> str:
    if not lines:
        if side is not None and location["heading"] is None:
            return "進行方向が分からないため、左右では絞り込めませんでした。"
        return "該当する場所は見つかりませんでした。"
    header = "現在地から近い順（距離と方角は計算済み。言い換えずにそのまま使うこと）:"
    if location["heading"] is None:
        header += "\n進行方向が分からないため、左右は付けていません。"
    return header + "\n" + "\n".join(f"- {line}" for line in lines)


_NO_LOCATION = "現在地が分からないため、周辺を探せません。"
_FAILED = "周辺の検索に失敗しました。"


@tool(context=True)
def search_nearby_places(
    kind: Kind,
    tool_context: ToolContext,
    side: Optional[Side] = None,
    radius_km: float = 5.0,
) -> str:
    """現在地の周辺にある場所を種類で探し、近い順に距離・方角・左右を返す。

    「右手に見える山は？」「近くのコンビニは？」「この辺に温泉ある？」のように、
    特定の名前ではなく種類で探すときに使う。店やチェーンの名前（マクドナルド等）は
    search_places_by_name を使う。現在地はシステムが自動で渡すので、座標は指定しない。

    Args:
        kind: 探す場所の種類。
        side: 「右手に見える」「左手の」のように向きを指定されたときだけ指定する。
        radius_km: 探す半径（km）。目に見えるものなら3〜5、道の駅やガソリンスタンドを
            探すなら20程度、山なら15程度。
    """
    location = read_location(tool_context.invocation_state)
    if location is None:
        return _NO_LOCATION
    categories = KINDS.get(kind)
    if not categories:
        return f"「{kind}」という種類では探せません。"

    radius_m = int(min(max(radius_km, MIN_RADIUS_KM), MAX_RADIUS_KM) * 1000)
    try:
        result = _get_client().search_nearby(
            # Longitude first - the reverse order silently searches elsewhere.
            QueryPosition=[location["longitude"], location["latitude"]],
            QueryRadius=radius_m,
            MaxResults=MAX_FETCHED if side else MAX_RETURNED * 2,
            Language="ja",
            Filter={"IncludeCategories": categories},
        )
    except Exception as error:  # noqa: BLE001 - the model answers without it
        print(f"search_nearby failed: {type(error).__name__}: {error}")
        return _FAILED

    lines = describe_places(result.get("ResultItems") or [], location, side)
    return _answer(lines, location, side)


@tool(context=True)
def search_places_by_name(
    name: str,
    tool_context: ToolContext,
    side: Optional[Side] = None,
) -> str:
    """店・チェーン・施設・地名を名前で探し、現在地から近い順に距離・方角・左右を返す。

    「一番近いマクドナルドは？」「セブンイレブンはどこ？」「芦ノ湖までどのくらい？」のように
    名前が分かっているときに使う。現在地はシステムが自動で渡すので、座標は指定しない。

    Args:
        name: 探す名前（例: マクドナルド、ENEOS、芦ノ湖）。地名や「近くの」は付けない。
        side: 「右手の」「左手の」のように向きを指定されたときだけ指定する。
    """
    location = read_location(tool_context.invocation_state)
    if location is None:
        return _NO_LOCATION
    if not name.strip():
        return "探す名前が空です。"

    try:
        result = _get_client().search_text(
            QueryText=name.strip(),
            # Longitude first, as above.
            BiasPosition=[location["longitude"], location["latitude"]],
            MaxResults=MAX_FETCHED if side else MAX_RETURNED * 2,
            Language="ja",
        )
    except Exception as error:  # noqa: BLE001 - the model answers without it
        print(f"search_text failed: {type(error).__name__}: {error}")
        return _FAILED

    items = result.get("ResultItems") or []
    # SearchText ranks by relevance first; the rider asked for the nearest.
    items = sorted(items, key=lambda item: item.get("Distance", float("inf")))
    lines = describe_places(items, location, side)
    return _answer(lines, location, side)
