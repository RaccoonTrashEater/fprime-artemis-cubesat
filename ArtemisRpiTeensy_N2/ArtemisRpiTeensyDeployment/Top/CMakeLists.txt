####
# F Prime CMakeLists.txt:
#
# SOURCES: list of source files (to be compiled)
# AUTOCODER_INPUTS: list of files to be passed to the autocoders
# DEPENDS: list of libraries that this module depends on
#
# More information in the F´ CMake API documentation:
# https://fprime.jpl.nasa.gov/latest/docs/reference/api/cmake/API/
#
####

set(NEUTRON2_TOPOLOGY_AUTOCODER_INPUTS
    "${CMAKE_CURRENT_LIST_DIR}/instances.fpp"
)
set(NEUTRON2_TOPOLOGY_DEPENDENCIES
    Fw_Logger
    ${NEUTRON2_DEPLOYMENT_CONFIG}
)
if (NEUTRON2_CDR_TCP)
    list(APPEND NEUTRON2_TOPOLOGY_AUTOCODER_INPUTS
        "${CMAKE_CURRENT_LIST_DIR}/instances.cdr_tcp.fpp"
        "${CMAKE_CURRENT_LIST_DIR}/topology.cdr_tcp.fpp"
    )
    list(APPEND NEUTRON2_TOPOLOGY_DEPENDENCIES
        Drv_TcpServer
    )
else()
    list(APPEND NEUTRON2_TOPOLOGY_AUTOCODER_INPUTS
        "${CMAKE_CURRENT_LIST_DIR}/topology.fpp"
    )
endif()

register_fprime_module(
    AUTOCODER_INPUTS
        ${NEUTRON2_TOPOLOGY_AUTOCODER_INPUTS}
    SOURCES
        "${CMAKE_CURRENT_LIST_DIR}/ArtemisRpiTeensyDeploymentTopology.cpp"
    DEPENDS
        ${NEUTRON2_TOPOLOGY_DEPENDENCIES}
)
