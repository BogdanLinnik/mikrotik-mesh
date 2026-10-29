# mesh-rejected: devices that the router disconnected because of the access-list (e.g. the min-signal rule),
# with the access point they were attached to and their last signal. Read-only, changes nothing.
# The script defines the global function $meshRejected. Global variables are lost on reboot.
# Text is ASCII-only on purpose: RouterOS terminals drop non-ASCII characters in scripts.
#
# Load:   /import file-name=mesh-rejected.rsc
# Run:    $meshRejected                      (time, MAC, device, access point, signal)
#         $meshRejected last=100
#         $meshRejected all=yes              (every disconnect, with a Reason column, for comparison)
#         $meshRejected clientMac=AA:BB:CC:DD:EE:FF
# Parameters (all optional):
#   last       show at most this many latest events (default 50)
#   all        yes = list every "disconnected" event with its reason, not only access-list ones
#   clientMac  only events of the client with this MAC address (colons or dashes, case-insensitive)
#
# IMPORTANT LIMITS (they come from what RouterOS writes to its log):
#  - The log has no reason called "min-signal". The only access-list reason is "access-list changed", and the
#    router writes it for EVERY edit of the access list, not only for the signal rule.
#  - A device that is refused while trying to connect (signal already below the limit) is not logged at all.
#  - The log lives in memory (1000 lines, wireless events fill it in a few hours) and is cleared on reboot.
#  - The access point is found from the radio name in the log line (cap-wifiN); if that radio no longer exists
#    (a CAP reconnected and got new radio names) the AP is shown as "?".

:global meshRejected do={
  :local lastN 50
  :if ([:typeof $last] != "nothing") do={ :set lastN [:tonum $last] }
  :if ($lastN < 1) do={ :put "Error: last must be at least 1"; :return "" }
  :local showAll false
  :if ([:typeof $all] != "nothing") do={ :if ([:tostr $all] = "yes" || [:tostr $all] = "true") do={ :set showAll true } }

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
  :local rows ({})
  :local count 0
  :local m ""
  :local mac ""
  :local at 0
  :local par 0
  :local radio ""
  :local d 0
  :local sg 0
  :local reason ""
  :local info ({})
  :local rid ({})
  :foreach id in=[/log find where topics~"wireless" and message~"disconnected, "] do={
    :set m [/log get $id message]
    :set d [:find $m "disconnected, "]
    :set sg [:find $m ", signal strength "]
    :set at [:find $m "@"]
    :set par [:find $m "("]
    :if ([:typeof $d] != "nil" && [:typeof $sg] != "nil" && [:typeof $at] != "nil" && [:typeof $par] != "nil") do={
      :set mac [:pick $m 0 $at]
      :set reason [:pick $m ($d + 14) $sg]
      :if (($showAll || [:typeof [:find $reason "access-list"]] != "nil") && ($cm = "" || $cm = $mac)) do={
        :set radio [:pick $m ($at + 1) $par]
        # Radio cap-wifiN -> access point name (before @ in its "cap" field); the router's own radio has no such field
        :if ([:typeof ($radioAp->$radio)] = "nothing") do={
          :set rid [/interface wifi find where name=$radio]
          :if ([:len $rid] = 0) do={ :set ($radioAp->$radio) "?" } else={
            :set info [/interface wifi get [:pick $rid 0]]
            :if ([:typeof ($info->"cap")] = "nothing") do={ :set ($radioAp->$radio) $localName } else={ :set ($radioAp->$radio) [:pick ($info->"cap") 0 [:find ($info->"cap") "@"]] }
          }
        }
        :set ($rows->$count) ({"time"=[/log get $id time]; "mac"=$mac; "ap"=($radioAp->$radio); "sig"=[:pick $m ($sg + 18) [:len $m]]; "reason"=$reason})
        :set count ($count + 1)
      }
    }
  }

  :local first ""
  :local w [/log find where topics~"wireless"]
  :if ([:len $w] > 0) do={ :set first [/log get [:pick $w 0] time] }
  :put ""
  :if ($showAll) do={ :put "All Wi-Fi disconnects found in the router log" } else={ :put "Wi-Fi disconnects caused by the access-list (router log)" }
  :put ("Log covers Wi-Fi events since " . $first . ". Events found: " . $count . ", showing the latest " . $lastN . " at most.")
  :put ""
  :if ($count = 0) do={
    :put "Nothing found in the log. See the limits at the top of mesh-rejected.rsc: refused connection attempts are not logged."
    :return ""
  }
  # The Reason column is shown only with all=yes; for access-list events it is always the same
  :local hdr ([$padL s="Time" w=19] . "  " . [$padL s="MAC" w=17] . "  " . [$padL s="Device" w=24] . "  " . [$padL s="AP" w=7] . "  " . [$padR s="Signal" w=6])
  :if ($showAll) do={ :set hdr ($hdr . "  Reason") }
  :put $hdr
  :local start 0
  :if ($count > $lastN) do={ :set start ($count - $lastN) }
  :local who ({})
  :local line ""
  :for i from=$start to=($count - 1) do={
    :set who [$lookup m=($rows->$i->"mac")]
    :set line ([$padL s=($rows->$i->"time") w=19] . "  " . [$padL s=($rows->$i->"mac") w=17] . "  " . [$padL s=($who->"name") w=24] . "  " . [$padL s=($rows->$i->"ap") w=7] . "  " . [$padR s=($rows->$i->"sig") w=6])
    :if ($showAll) do={ :set line ($line . "  " . ($rows->$i->"reason")) }
    :put $line
  }
  :return ""
}
