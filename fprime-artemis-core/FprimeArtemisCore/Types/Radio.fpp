module Components {
  enum RadioState : U8 { OFF, IDLE, RX, TX, FAULT }
  array RadioBytes = [49] U8
  struct RadioPacket { bytes: RadioBytes, length: U8, to: U8, from: U8, network: U8, version: U8 }
  struct RadioStatus { $state: RadioState, rssi: I16, crcDrops: U32 }
  port RadioPower(enabled: bool) -> bool
  port RadioSend($packet: RadioPacket) -> bool
  port RadioReceive(ref $packet: RadioPacket) -> bool
  port RadioStatusGet() -> RadioStatus
}
