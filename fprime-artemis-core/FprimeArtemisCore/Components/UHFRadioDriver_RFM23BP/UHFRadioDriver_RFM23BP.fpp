module Components {
  @ RFM23BP hardware executor. All calls must come from the radio worker.
  passive component UHFRadioDriver_RFM23BP {
    sync input port power: RadioPower
    sync input port $send: RadioSend
    sync input port receive: RadioReceive
    sync input port status: RadioStatusGet
  }
}
