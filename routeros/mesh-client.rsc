# mesh-client: which access point a device is connected to, its signal and the TX/RX at this very moment.
# No sampling over time: the values are what the router reports right now (use mesh-traffic* / mesh-live for averages).
# Read-only, changes nothing. The script defines the global function $meshClient.
# Global variables are lost on reboot. Text is ASCII-only on purpose: RouterOS terminals drop non-ASCII characters in scripts.
#
# Load:   /import file-name=mesh-client.rsc
# Run:    $meshClient clientMac=AA:BB:CC:DD:EE:FF
#         $meshClient                       (all Wi-Fi clients, largest TX first)
# Parameters (optional):
#   clientMac  only the client with this MAC address (colons or dashes, case-insensitive)
# TX: access point -> device (download), RX: device -> access point (upload).
# Rates are the instantaneous values the router keeps for each client, so they can read 0bps between bursts.

:global meshClient do={
  # Character replacement: every char found in string "from" is replaced by the char at the same position in "to"
  :local conv do={
    :local out ""
    :for i from=0 to=([:len $s] - 1) do={
      :local c [:pick $s $i ($i + 1)]
      :local p [:find $from $c]
      :if ([:typeof $p] != "nil") do={ :set c [:pick $to $p ($p + 1)] }
      :set out ($out . $c)
    }
    :return $out
  }
  :local UP "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
  :local LOW "abcdefghijklmnopqrstuvwxyz"

  :local padL do={ :local o [:tostr $s]; :while ([:len $o] < $w) do={ :set o ($o . " ") }; :return $o }
  :local padR do={ :local o [:tostr $s]; :while ([:len $o] < $w) do={ :set o (" " . $o) }; :return $o }

  # Bits per second -> text (-1 = unknown)
  :local fmt do={
    :if ($v < 0) do={ :return "-" }
    :if ($v >= 1000000000) do={ :local t ($v / 100000000); :return (($t / 10) . "." . ($t % 10) . "Gbps") }
    :if ($v >= 1000000) do={ :local t ($v / 100000); :return (($t / 10) . "." . ($t % 10) . "Mbps") }
    :if ($v >= 1000) do={ :local t ($v / 100); :return (($t / 10) . "." . ($t % 10) . "kbps") }
    :return ($v . "bps")
  }

  # Host name and IP of a client from its DHCP lease
  :local lookup do={
    :local r ({"name"=$m; "ip"=""})
    :local ls [/ip dhcp-server lease find where mac-address=$m]
    :if ([:len $ls] > 0) do={
      :local info [/ip dhcp-server lease get [:pick $ls 0]]
      :if ([:typeof ($info->"host-name")] != "nothing") do={
        :if (($info->"host-name") != "") do={ :set ($r->"name") ($info->"host-name") }
      }
      :set ($r->"ip") ($info->"address")
    }
    :return $r
  }

  :local cm ""
  :if ([:typeof $clientMac] != "nothing") do={
    :set cm [$conv s=[:tostr $clientMac] from="abcdef-" to="ABCDEF:"]
    :if ([:len $cm] != 17) do={ :put "Error: clientMac must look like AA:BB:CC:DD:EE:FF"; :return "" }
  }

  :local localName [/system identity get name]
  :local radioAp ({})
  :local items ({})
  :local ids [/interface wifi registration-table find]
  :if ($cm != "") do={ :set ids [/interface wifi registration-table find where mac-address=$cm] }
  :foreach r in=$ids do={
    :local mac [/interface wifi registration-table get $r mac-address]
    :local ifc [/interface wifi registration-table get $r interface]
    # Radio cap-wifiN belongs to the access point named before @ in its "cap" field; the router's own radio has no such field
    :if ([:typeof ($radioAp->$ifc)] = "nothing") do={
      :local info [/interface wifi get [/interface wifi find where name=$ifc]]
      :local cap ($info->"cap")
      :if ([:typeof $cap] = "nothing") do={ :set ($radioAp->$ifc) $localName } else={ :set ($radioAp->$ifc) [:pick $cap 0 [:find $cap "@"]] }
    }
    :set ($items->$mac) ({"ap"=($radioAp->$ifc); "band"=[/interface wifi registration-table get $r band]; "sig"=[/interface wifi registration-table get $r signal]; "tx"=[/interface wifi registration-table get $r tx-bits-per-second]; "rx"=[/interface wifi registration-table get $r rx-bits-per-second]})
  }

  :if ([:len $items] = 0) do={
    :if ($cm != "") do={ :put ("Client " . $cm . " is not connected over Wi-Fi (wired devices have no per-client counters).") } else={ :put "No Wi-Fi clients." }
    :return ""
  }
  :put ([$padL s="Device" w=30] . "  " . [$padL s="IP" w=15] . "  " . [$padL s="MAC" w=17] . "  " . [$padL s="AP" w=7] . "  " . [$padL s="Band" w=8] . "  " . [$padR s="Signal" w=6] . "  " . [$padR s="TX" w=11] . "  " . [$padR s="RX" w=11])

  # Largest TX first (selection sort)
  :local taken ({})
  :local left [:len $items]
  :local bestK ""
  :local bestV 0
  :while ($left > 0) do={
    :set bestK ""
    :set bestV (-1)
    :foreach k,v in=$items do={
      :if ([:typeof ($taken->$k)] = "nothing" && ($v->"tx") > $bestV) do={ :set bestV ($v->"tx"); :set bestK $k }
    }
    :local v ($items->$bestK)
    :local who [$lookup m=$bestK]
    :put ([$padL s=($who->"name") w=30] . "  " . [$padL s=($who->"ip") w=15] . "  " . [$padL s=$bestK w=17] . "  " . [$padL s=($v->"ap") w=7] . "  " . [$padL s=($v->"band") w=8] . "  " . [$padR s=($v->"sig") w=6] . "  " . [$padR s=[$fmt v=($v->"tx")] w=11] . "  " . [$padR s=[$fmt v=($v->"rx")] w=11])
    :set ($taken->$bestK) 1
    :set left ($left - 1)
  }
  :return ""
}
