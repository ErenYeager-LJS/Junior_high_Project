import json
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


# WEATHER_TIMEOUT_SECONDS 是每次天气网络请求允许等待的最长时间。
WEATHER_TIMEOUT_SECONDS = 12
# WEATHER_REQUEST_ATTEMPTS 是遇到瞬时网络中断时的总尝试次数。
WEATHER_REQUEST_ATTEMPTS = 3
# GEOCODING_API_URL 用于把“南京”等城市名换成经纬度。
GEOCODING_API_URL = "https://geocoding-api.open-meteo.com/v1/search"
# FORECAST_API_URL 用于按经纬度读取当前天气观测。
FORECAST_API_URL = "https://api.open-meteo.com/v1/forecast"
# WEATHER_CODE_LABELS 把 Open-Meteo 的 WMO 天气代码转换成通俗中文。
WEATHER_CODE_LABELS = {
    0: "晴",
    1: "大致晴朗",
    2: "局部多云",
    3: "阴",
    45: "有雾",
    48: "有雾凇",
    51: "小毛毛雨",
    53: "毛毛雨",
    55: "较强毛毛雨",
    56: "轻微冻毛毛雨",
    57: "冻毛毛雨",
    61: "小雨",
    63: "中雨",
    65: "大雨",
    66: "轻微冻雨",
    67: "冻雨",
    71: "小雪",
    73: "中雪",
    75: "大雪",
    77: "米雪",
    80: "小阵雨",
    81: "阵雨",
    82: "强阵雨",
    85: "小阵雪",
    86: "强阵雪",
    95: "雷雨",
    96: "雷雨伴小冰雹",
    99: "雷雨伴冰雹",
}


# WeatherError 表示可以安全显示给网页用户的天气查询错误。
class WeatherError(Exception):
    pass


# request_json 请求一个 JSON 接口，并统一处理网络和数据格式错误。
def request_json(base_url, parameters):
    # query_string 是经过安全编码的 URL 查询参数。
    query_string = urlencode(parameters)
    # weather_request 带有项目标识，方便公共服务识别请求来源。
    weather_request = Request(
        f"{base_url}?{query_string}",
        headers={"User-Agent": "ESP8266-Classroom-Console/1.0"},
    )
    # last_error 保存最后一次瞬时网络错误，全部重试失败时用于保留错误原因。
    last_error = None
    for attempt in range(WEATHER_REQUEST_ATTEMPTS):
        try:
            with urlopen(weather_request, timeout=WEATHER_TIMEOUT_SECONDS) as response:
                # response_data 是接口返回并解析后的 JSON 对象。
                response_data = json.loads(response.read().decode("utf-8"))
            break
        except HTTPError as error:
            raise WeatherError(f"天气服务请求失败，HTTP {error.code}。") from error
        except (URLError, TimeoutError, json.JSONDecodeError) as error:
            last_error = error
            if attempt == WEATHER_REQUEST_ATTEMPTS - 1:
                raise WeatherError("实时天气服务暂时无法连接。") from last_error
    if not isinstance(response_data, dict):
        raise WeatherError("实时天气服务返回了无法识别的数据。")
    return response_data


# lookup_city 查询城市的标准名称、行政区和经纬度。
def lookup_city(city_name):
    # normalized_city 是去除首尾空白后的城市名称。
    normalized_city = city_name.strip()
    if not normalized_city:
        raise WeatherError("请告诉我想查询哪个城市的天气。")
    # geocoding_data 保存城市检索结果。
    geocoding_data = request_json(
        GEOCODING_API_URL,
        {"name": normalized_city, "count": 1, "language": "zh", "format": "json"},
    )
    # results 是按匹配程度排序的候选城市列表。
    results = geocoding_data.get("results")
    if not isinstance(results, list) or not results:
        raise WeatherError(f"没有找到“{normalized_city}”，请换一种城市名称。")
    # place 是匹配程度最高的城市。
    place = results[0]
    try:
        return {
            "name": str(place["name"]),
            "admin1": str(place.get("admin1") or ""),
            "country": str(place.get("country") or ""),
            "latitude": float(place["latitude"]),
            "longitude": float(place["longitude"]),
        }
    except (KeyError, TypeError, ValueError) as error:
        raise WeatherError("城市定位结果缺少必要字段。") from error


# get_current_weather 获取指定城市当前时刻的天气数据。
def get_current_weather(city_name):
    # place 保存城市名称和天气接口需要的坐标。
    place = lookup_city(city_name)
    # forecast_data 保存 Open-Meteo 返回的当前天气观测。
    forecast_data = request_json(
        FORECAST_API_URL,
        {
            "latitude": place["latitude"],
            "longitude": place["longitude"],
            "current": (
                "temperature_2m,apparent_temperature,relative_humidity_2m,"
                "precipitation,weather_code,wind_speed_10m"
            ),
            "daily": (
                "weather_code,temperature_2m_max,temperature_2m_min,"
                "precipitation_probability_max"
            ),
            "forecast_days": 1,
            "timezone": "auto",
        },
    )
    # current 是当前观测值集合。
    current = forecast_data.get("current")
    # daily 是当地今天的预报集合。
    daily = forecast_data.get("daily")
    if not isinstance(current, dict) or not isinstance(daily, dict):
        raise WeatherError("天气服务没有返回完整观测。")
    try:
        # weather_code 是 WMO 标准天气现象编号。
        weather_code = int(current["weather_code"])
        # daily_weather_code 是今天预报采用的 WMO 天气现象编号。
        daily_weather_code = int(daily["weather_code"][0])
        return {
            "city": place["name"],
            "admin1": place["admin1"],
            "country": place["country"],
            "observed_at": str(current["time"]),
            "condition": WEATHER_CODE_LABELS.get(weather_code, f"天气代码 {weather_code}"),
            "temperature_c": float(current["temperature_2m"]),
            "apparent_temperature_c": float(current["apparent_temperature"]),
            "humidity_percent": int(current["relative_humidity_2m"]),
            "precipitation_mm": float(current["precipitation"]),
            "wind_speed_kmh": float(current["wind_speed_10m"]),
            "today_condition": WEATHER_CODE_LABELS.get(
                daily_weather_code, f"天气代码 {daily_weather_code}"
            ),
            "today_max_c": float(daily["temperature_2m_max"][0]),
            "today_min_c": float(daily["temperature_2m_min"][0]),
            "today_precipitation_probability_percent": int(
                daily["precipitation_probability_max"][0]
            ),
            "source": "Open-Meteo",
        }
    except (KeyError, TypeError, ValueError) as error:
        raise WeatherError("天气观测缺少必要字段。") from error
