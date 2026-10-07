module RadioComms {
  instance driver: Components.UHFRadioDriver_RFM23BP base id 0x10301000
  instance manager: Components.UHFRadioManager base id 0x10302000
  topology Subtopology {
    instance driver
    instance manager
    connections RadioHardware {
      manager.driverPower -> driver.power
      manager.driverSend -> driver.$send
      manager.driverReceive -> driver.receive
      manager.driverStatus -> driver.status
    }
    port dataIn = manager.dataIn
    port dataReturnOut = manager.dataReturnOut
    port dataOut = manager.dataOut
    port dataReturnIn = manager.dataReturnIn
    port comStatusOut = manager.comStatusOut
    port allocate = manager.allocate
    port deallocate = manager.deallocate
    port powerRequestIn = manager.powerRequestIn
  }
}
