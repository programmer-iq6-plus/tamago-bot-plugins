-- Plugin "saklar": one relay on a GPIO output (example of the plugin API v2).
-- The pin is chosen by the person in the app ("relay" role); the board starts
-- it at 0 (off) and asks aloud before saklar_nyalakan/saklar_matikan run.

local function keadaan()
  return tamago.gpio_read("relay") == 1 and "nyala" or "mati"
end

function saklar_nyalakan()
  tamago.gpio_write("relay", 1)
  return { saklar = keadaan() }
end

function saklar_matikan()
  tamago.gpio_write("relay", 0)
  return { saklar = keadaan() }
end

function saklar_status()
  return { saklar = keadaan() }
end
