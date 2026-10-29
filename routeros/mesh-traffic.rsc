# mesh-traffic: full load report per access point (Wi-Fi clients, access point uplink ports, wired devices).
# Same as `python3 traffic.py`, but runs directly on the RB4011 (read-only, changes nothing).
# The script defines the global function $meshTraffic. Global variables are lost on reboot.
# Text is ASCII-only on purpose: RouterOS terminals drop non-ASCII characters in scripts.
#
# Load:   /import file-name=mesh-traffic.rsc
# Run:    $meshTraffic
#         $meshTraffic duration=60 showZeros=yes
#         $meshTraffic clientMac=AA:BB:CC:DD:EE:FF
# Parameters (all optional):
#   duration   measurement time in seconds, 1-300 (default 30)
#   showZeros  yes = also list clients whose TX and RX are both 0bps (hidden by default)
#   clientMac  only the client with this MAC address (colons or dashes, case-insensitive); shown even without traffic
# TX: access point -> device (download), RX: device -> access point (upload).
# The "port" line is the RB4011 port the access point is plugged into: all traffic of that point, including the
# wired devices behind it, which have no per-client counters and are only listed.

:global meshTraffic do={
  :local dur 30
  :if ([:typeof $duration] != "nothing") do={ :set dur [:tonum $duration] }
  :if ($dur < 1 || $dur > 300) do={ :put "Error: duration must be 1-300 seconds"; :return "" }
  :local zeros false
  :if ([:typeof $showZeros] != "nothing") do={ :if ([:tostr $showZeros] = "yes" || [:tostr $showZeros] = "true") do={ :set zeros true } }

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

  # Counter snapshot: t = router time, c = {MAC: {ap, band, sig, tx, rx}} of Wi-Fi clients, p = {AP: {rx, tx}} of uplink ports
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
      :if ([:typeof ($radioAp->$ifc)] = "nothing") do={
        :local info [/interface wifi get [/interface wifi find where name=$ifc]]
        :local cap ($info->"cap")
        :if ([:typeof $cap] = "nothing") do={ :set ($radioAp->$ifc) $localName } else={ :set ($radioAp->$ifc) [:pick $cap 0 [:find $cap "@"]] }
      }
      :local b [/interface wifi registration-table get $r bytes]
      :local comma [:find $b ","]
      :set ($res->$mac) ({"ap"=($radioAp->$ifc); "band"=[/interface wifi registration-table get $r band]; "sig"=[/interface wifi registration-table get $r signal]; "tx"=[:tonum [:pick $b 0 $comma]]; "rx"=[:tonum [:pick $b ($comma + 1) [:len $b]]]})
    }
    :local pr ({})
    :foreach n,p in=$ports do={
      :local id [/interface find where name=$p]
      :if ([:len $id] > 0) do={ :set ($pr->$n) ({"rx"=[/interface get [:pick $id 0] rx-byte]; "tx"=[/interface get [:pick $id 0] tx-byte]}) }
    }
    :return ({"t"=$t; "c"=$res; "p"=$pr})
  }

  # --- Parameter checks
  :local cm ""
  :if ([:typeof $clientMac] != "nothing") do={
    :set cm [$conv s=[:tostr $clientMac] from="abcdef-" to="ABCDEF:"]
    :if ([:len $cm] != 17) do={ :put "Error: clientMac must look like AA:BB:CC:DD:EE:FF"; :return "" }
    :set zeros true
  }

  # --- Access points: the router itself first, then every CAP known to CAPsMAN
  :local apNames [:toarray [/system identity get name]]
  :local apMac ({})
  :local apIp ({})
  :local apPort ({})
  :local ports ({})
  :local localIp ""
  :local addr [/ip address find where interface="bridge"]
  :if ([:len $addr] > 0) do={
    :set localIp [/ip address get [:pick $addr 0] address]
    :set localIp [:pick $localIp 0 [:find $localIp "/"]]
  }
  :set ($apIp->[/system identity get name]) $localIp
  :foreach c in=[/interface wifi capsman remote-cap find] do={
    :local n [/interface wifi capsman remote-cap get $c identity]
    :local bm [/interface wifi capsman remote-cap get $c base-mac]
    :set apNames ($apNames, $n)
    :set ($apMac->$n) $bm
    :set ($apIp->$n) ([$lookup m=$bm]->"ip")
    :local hs [/interface bridge host find where mac-address=$bm and local=no]
    :if ([:len $hs] > 0) do={
      :local pt [/interface bridge host get [:pick $hs 0] on-interface]
      :set ($apPort->$n) $pt
      :set ($ports->$n) $pt
    }
  }

  :put ("Measuring for " . $dur . " s...")
  :local s1 [$snap cm=$cm ports=$ports]
  :delay ($dur . "s")
  :local s2 [$snap cm=$cm ports=$ports]
  :local m1 ($s1->"c")
  :local m2 ($s2->"c")
  :local ms ([:tonsec (($s2->"t") - ($s1->"t"))] / 1000000)
  :if ($ms < 1) do={ :set ms 1 }

  # Rate = counter growth between the snapshots; -1 if unknown (new client, reset counter)
  :local items ({})
  :foreach mac,c in=$m2 do={
    :local p ($m1->$mac)
    :local tx (-1)
    :local rx (-1)
    :if ([:typeof $p] = "array") do={
      :if (($c->"tx") >= ($p->"tx")) do={ :set tx ((($c->"tx") - ($p->"tx")) * 8000 / $ms) }
      :if (($c->"rx") >= ($p->"rx")) do={ :set rx ((($c->"rx") - ($p->"rx")) * 8000 / $ms) }
    }
    :set ($items->$mac) ({"ap"=($c->"ap"); "band"=($c->"band"); "sig"=($c->"sig"); "tx"=$tx; "rx"=$rx})
  }

  :put ""
  :local title ("Load over " . $dur . " s")
  :if ($cm != "") do={ :set title ($title . ", client " . $cm) }
  :put ($title . ". TX: to the device (download), RX: from the device (upload).")
  :put ""

  :local found false
  :local line ""
  :local taken ({})
  :local pending 0
  :local bestK ""
  :local bestV 0
  :local sc 0
  :local nClients 0
  :local sumTx 0
  :local sumRx 0
  :local hidden 0
  :local pt ""
  :local pa ({})
  :local wired ({})
  :foreach apn in=$apNames do={
    # Wi-Fi clients of this access point and their totals
    :set nClients 0
    :set sumTx 0
    :set sumRx 0
    :set hidden 0
    :set pending 0
    :set taken ({})
    :foreach k,v in=$items do={
      :if (($v->"ap") = $apn) do={
        :set nClients ($nClients + 1)
        :if (($v->"tx") > 0) do={ :set sumTx ($sumTx + ($v->"tx")) }
        :if (($v->"rx") > 0) do={ :set sumRx ($sumRx + ($v->"rx")) }
        :if ($zeros || ($v->"tx") > 0 || ($v->"rx") > 0) do={ :set pending ($pending + 1) } else={ :set hidden ($hidden + 1) }
      }
    }
    # Wired devices: hosts on the port of this access point that are not Wi-Fi clients and not access points
    :set wired ({})
    :set pt ($apPort->$apn)
    :if ([:typeof $pt] != "nothing") do={
      :foreach h in=[/interface bridge host find where on-interface=$pt and local=no] do={
        :local hm [/interface bridge host get $h mac-address]
        :local isAp false
        :foreach an in=$apNames do={ :if (($apMac->$an) = $hm) do={ :set isAp true } }
        :if ([:typeof ($m2->$hm)] = "nothing" && !$isAp && ($cm = "" || $cm = $hm)) do={ :set ($wired->$hm) 1 }
      }
    }
    :if ($cm = "" || $nClients > 0 || [:len $wired] > 0) do={
      :set found true
      :local head $apn
      :if (($apIp->$apn) != "") do={ :set head ($head . " (" . ($apIp->$apn) . ")") }
      :put $head
      :if ([:typeof $pt] != "nothing") do={
        :set pa ($s2->"p")
        :local q1 (($s1->"p")->$apn)
        :local q2 ($pa->$apn)
        :local ptx (-1)
        :local prx (-1)
        :if ([:typeof $q1] = "array" && [:typeof $q2] = "array") do={
          :if (($q2->"tx") >= ($q1->"tx")) do={ :set ptx ((($q2->"tx") - ($q1->"tx")) * 8000 / $ms) }
          :if (($q2->"rx") >= ($q1->"rx")) do={ :set prx ((($q2->"rx") - ($q1->"rx")) * 8000 / $ms) }
        }
        :put ("  port " . $pt . " to the access point: TX " . [$fmt v=$ptx] . ", RX " . [$fmt v=$prx])
      }
      :put ("  Wi-Fi clients: " . $nClients . ", total TX " . [$fmt v=$sumTx] . ", RX " . [$fmt v=$sumRx])
      :if ($pending > 0) do={
        :put ("    " . [$padL s="Device" w=30] . "  " . [$padL s="IP" w=15] . "  " . [$padL s="Band" w=8] . "  " . [$padR s="Signal" w=6] . "  " . [$padR s="TX" w=11] . "  " . [$padR s="RX" w=11])
      }
      # Largest first by TX + RX (selection sort)
      :while ($pending > 0) do={
        :set bestK ""
        :set bestV (-1)
        :foreach k,v in=$items do={
          :if (($v->"ap") = $apn && [:typeof ($taken->$k)] = "nothing" && ($zeros || ($v->"tx") > 0 || ($v->"rx") > 0)) do={
            :set sc 0
            :if (($v->"tx") > 0) do={ :set sc ($sc + ($v->"tx")) }
            :if (($v->"rx") > 0) do={ :set sc ($sc + ($v->"rx")) }
            :if ($sc > $bestV) do={ :set bestV $sc; :set bestK $k }
          }
        }
        :if ($bestK = "") do={ :set pending 0 } else={
          :local v ($items->$bestK)
          :local who [$lookup m=$bestK]
          :put ("    " . [$padL s=($who->"name") w=30] . "  " . [$padL s=($who->"ip") w=15] . "  " . [$padL s=($v->"band") w=8] . "  " . [$padR s=($v->"sig") w=6] . "  " . [$padR s=[$fmt v=($v->"tx")] w=11] . "  " . [$padR s=[$fmt v=($v->"rx")] w=11])
          :set ($taken->$bestK) 1
          :set pending ($pending - 1)
        }
      }
      :if ($hidden > 0) do={ :put ("    " . $hidden . " more without traffic hidden (showZeros=yes)") }
      :if ([:len $wired] > 0) do={
        :put "  Wired (or without a Wi-Fi record), no per-client counters:"
        :foreach hm,x in=$wired do={
          :local who [$lookup m=$hm]
          :put ("    " . ($who->"name") . "  " . ($who->"ip") . "  " . $hm)
        }
      }
      :put ""
    }
  }
  :if (!$found) do={ :put ("Client " . $cm . " not found among the connected clients.") }
  :return ""
}
