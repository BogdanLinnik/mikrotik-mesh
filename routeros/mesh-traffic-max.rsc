# mesh-traffic-max: top 10 Wi-Fi clients by load (TX), the access point is a separate column.
# Same as `python3 traffic.py --max-only`, but runs directly on the RB4011 (read-only, changes nothing).
# The script defines the global function $meshTrafficMax. Global variables are lost on reboot.
# Text is ASCII-only on purpose: RouterOS terminals drop non-ASCII characters in scripts.
#
# Load:   /import file-name=mesh-traffic-max.rsc
# Run:    $meshTrafficMax
#         $meshTrafficMax duration=60 source=ax3-1
#         $meshTrafficMax clientMac=AA:BB:CC:DD:EE:FF
# Parameters (all optional):
#   duration   measurement time in seconds, 1-300 (default 30)
#   source     only clients of this access point: rb4011 (the router name), ac3-1, ax3-2 ... (case-insensitive)
#   clientMac  only the client with this MAC address (colons or dashes, case-insensitive)
# TX: access point -> device (download), RX: device -> access point (upload).

:global meshTrafficMax do={
  :local dur 30
  :if ([:typeof $duration] != "nothing") do={ :set dur [:tonum $duration] }
  :if ($dur < 1 || $dur > 300) do={ :put "Error: duration must be 1-300 seconds"; :return "" }

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

  # Counter snapshot of Wi-Fi clients: t = router time, c = {MAC: {ap, band, sig, tx, rx}}
  :local snap do={
    :local res ({})
    :local radioAp ({})
    :local localName [/system identity get name]
    :local t [:timestamp]
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
      :local b [/interface wifi registration-table get $r bytes]
      :local comma [:find $b ","]
      :set ($res->$mac) ({"ap"=($radioAp->$ifc); "band"=[/interface wifi registration-table get $r band]; "sig"=[/interface wifi registration-table get $r signal]; "tx"=[:tonum [:pick $b 0 $comma]]; "rx"=[:tonum [:pick $b ($comma + 1) [:len $b]]]})
    }
    :return ({"t"=$t; "c"=$res})
  }

  # --- Parameter checks
  :local cm ""
  :if ([:typeof $clientMac] != "nothing") do={
    :set cm [$conv s=[:tostr $clientMac] from="abcdef-" to="ABCDEF:"]
    :if ([:len $cm] != 17) do={ :put "Error: clientMac must look like AA:BB:CC:DD:EE:FF"; :return "" }
  }
  :local src ""
  :if ([:typeof $source] != "nothing") do={
    :local names [:toarray [/system identity get name]]
    :foreach c in=[/interface wifi capsman remote-cap find] do={ :set names ($names, [/interface wifi capsman remote-cap get $c identity]) }
    :local want [$conv s=[:tostr $source] from=$UP to=$LOW]
    :foreach n in=$names do={ :if ([$conv s=$n from=$UP to=$LOW] = $want) do={ :set src $n } }
    :if ($src = "") do={ :put ("Error: access point " . $source . " not found. Available: " . [:tostr $names]); :return "" }
  }

  :put ("Measuring for " . $dur . " s...")
  :local s1 [$snap cm=$cm]
  :delay ($dur . "s")
  :local s2 [$snap cm=$cm]
  :local m1 ($s1->"c")
  :local m2 ($s2->"c")
  :local ms ([:tonsec (($s2->"t") - ($s1->"t"))] / 1000000)
  :if ($ms < 1) do={ :set ms 1 }

  # Rate = counter growth between the snapshots; -1 if the client was missing in the first snapshot or its counter was reset
  :local items ({})
  :foreach mac,c in=$m2 do={
    :if ($src = "" || ($c->"ap") = $src) do={
      :local p ($m1->$mac)
      :local tx (-1)
      :local rx (-1)
      :if ([:typeof $p] = "array") do={
        :if (($c->"tx") >= ($p->"tx")) do={ :set tx ((($c->"tx") - ($p->"tx")) * 8000 / $ms) }
        :if (($c->"rx") >= ($p->"rx")) do={ :set rx ((($c->"rx") - ($p->"rx")) * 8000 / $ms) }
      }
      :set ($items->$mac) ({"ap"=($c->"ap"); "band"=($c->"band"); "sig"=($c->"sig"); "tx"=$tx; "rx"=$rx})
    }
  }

  :put ""
  :local title ("Load over " . $dur . " s, top 10 clients by TX")
  :if ($src != "") do={ :set title ($title . " on " . $src) }
  :if ($cm != "") do={ :set title ($title . ", client " . $cm) }
  :put ($title . ".")
  :put "TX: to the device (download), RX: from the device (upload)."
  :put ""
  :if ([:len $items] = 0) do={
    :put "No such clients among the connected Wi-Fi clients (wired devices have no counters)."
    :return ""
  }
  :put ([$padL s="Device" w=30] . "  " . [$padL s="IP" w=15] . "  " . [$padL s="AP" w=7] . "  " . [$padL s="Band" w=8] . "  " . [$padR s="Signal" w=6] . "  " . [$padR s="TX" w=11] . "  " . [$padR s="RX" w=11])

  # Pick the 10 largest by TX (selection sort)
  :local taken ({})
  :local shown 0
  :local bestK ""
  :local bestV 0
  :local sc 0
  :while ($shown < 10) do={
    :set bestK ""
    :set bestV (-1)
    :foreach k,v in=$items do={
      :if ([:typeof ($taken->$k)] = "nothing") do={
        :set sc ($v->"tx")
        :if ($sc < 0) do={ :set sc 0 }
        :if ($sc > $bestV) do={ :set bestV $sc; :set bestK $k }
      }
    }
    :if ($bestK = "") do={ :set shown 10 } else={
      :local v ($items->$bestK)
      :local who [$lookup m=$bestK]
      :put ([$padL s=($who->"name") w=30] . "  " . [$padL s=($who->"ip") w=15] . "  " . [$padL s=($v->"ap") w=7] . "  " . [$padL s=($v->"band") w=8] . "  " . [$padR s=($v->"sig") w=6] . "  " . [$padR s=[$fmt v=($v->"tx")] w=11] . "  " . [$padR s=[$fmt v=($v->"rx")] w=11])
      :set ($taken->$bestK) 1
      :set shown ($shown + 1)
    }
  }
  :return ""
}
