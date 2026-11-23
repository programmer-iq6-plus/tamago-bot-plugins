-- Plugin "cuaca": weather from Open-Meteo (https://open-meteo.com, no key).
-- Example of the plugin API v1: http_get, json_decode, store_get/store_set.

-- WMO weather codes, as Open-Meteo returns them
local KONDISI = {
  [0] = "cerah", [1] = "cerah berawan", [2] = "berawan sebagian", [3] = "mendung",
  [45] = "berkabut", [48] = "berkabut tebal",
  [51] = "gerimis ringan", [53] = "gerimis", [55] = "gerimis lebat",
  [56] = "gerimis dingin", [57] = "gerimis dingin lebat",
  [61] = "hujan ringan", [63] = "hujan sedang", [65] = "hujan lebat",
  [66] = "hujan dingin", [67] = "hujan dingin lebat",
  [71] = "salju ringan", [73] = "salju", [75] = "salju lebat", [77] = "butiran salju",
  [80] = "hujan lokal ringan", [81] = "hujan lokal", [82] = "hujan lokal sangat lebat",
  [85] = "hujan salju", [86] = "hujan salju lebat",
  [95] = "badai petir", [96] = "badai petir dengan hujan es", [99] = "badai petir dengan hujan es lebat",
}

local function kondisi(code)
  return KONDISI[code] or ("kode cuaca " .. tostring(code))
end

local function urlencode(s)
  return (s:gsub("[^%w%-_%.~]", function(c) return string.format("%%%02X", string.byte(c)) end))
end

local function get_json(url)
  local status, body = tamago.http_get(url)
  if not status then
    return nil, "tidak bisa menghubungi layanan cuaca: " .. tostring(body)
  end
  if status ~= 200 then
    return nil, "layanan cuaca menjawab HTTP " .. status
  end
  local data, err = tamago.json_decode(body)
  if not data then
    return nil, "jawaban layanan cuaca tidak terbaca: " .. tostring(err)
  end
  return data
end

-- {name, lat, lon} of a city, or nil + reason
local function cari_kota(nama)
  local data, err = get_json("https://geocoding-api.open-meteo.com/v1/search?count=1&language=id&format=json&name="
    .. urlencode(nama))
  if not data then
    return nil, err
  end
  local r = data.results and data.results[1]
  if not r then
    return nil, "kota " .. nama .. " tidak ditemukan"
  end
  local nama_lengkap = r.name
  if r.admin1 and r.admin1 ~= r.name then
    nama_lengkap = nama_lengkap .. ", " .. r.admin1
  end
  if r.country then
    nama_lengkap = nama_lengkap .. ", " .. r.country
  end
  return { name = nama_lengkap, lat = r.latitude, lon = r.longitude }
end

local function hari(daily, i)
  return {
    tanggal = daily.time[i],
    kondisi = kondisi(daily.weather_code[i]),
    suhu_min_c = daily.temperature_2m_min[i],
    suhu_max_c = daily.temperature_2m_max[i],
    peluang_hujan_persen = daily.precipitation_probability_max and daily.precipitation_probability_max[i],
  }
end

function cuaca_kota(args)
  local nama = args.kota
  if type(nama) ~= "string" or nama:match("^%s*$") then
    nama = tamago.store_get("kota_terakhir")
  end
  if not nama then
    return { error = "kota belum disebut; tanyakan ke pengguna kota mana" }
  end

  local kota, err = cari_kota(nama)
  if not kota then
    return { error = err }
  end
  tamago.store_set("kota_terakhir", nama)

  local url = string.format("https://api.open-meteo.com/v1/forecast?latitude=%.4f&longitude=%.4f"
    .. "&current=temperature_2m,apparent_temperature,relative_humidity_2m,weather_code,wind_speed_10m"
    .. "&daily=weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max"
    .. "&timezone=auto&forecast_days=2", kota.lat, kota.lon)
  local data
  data, err = get_json(url)
  if not data then
    return { error = err }
  end
  local c = data.current
  return {
    kota = kota.name,
    sekarang = {
      waktu_setempat = c.time,
      kondisi = kondisi(c.weather_code),
      suhu_c = c.temperature_2m,
      terasa_seperti_c = c.apparent_temperature,
      kelembapan_persen = c.relative_humidity_2m,
      angin_kmh = c.wind_speed_10m,
    },
    hari_ini = hari(data.daily, 1),
    besok = hari(data.daily, 2),
    sumber = "Open-Meteo",
  }
end
