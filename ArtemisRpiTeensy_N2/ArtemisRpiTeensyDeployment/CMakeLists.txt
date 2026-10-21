#####
# 'ArtemisRpiTeensyDeployment' Deployment:
#
# This registers the 'ArtemisRpiTeensyDeployment' deployment to the build system. 
# Custom components that have not been added at the project-level should be added to 
# the list below.
#
#####

###
# Topology and Components
###

if (NEUTRON2_CDR_TCP)
    set(NEUTRON2_DEPLOYMENT_CONFIG CdrTcpConfig)
    add_fprime_subdirectory("${CMAKE_CURRENT_LIST_DIR}/CdrTcpConfig/")
elseif (NEUTRON2_LOCAL_YAMCS)
    set(NEUTRON2_DEPLOYMENT_CONFIG LocalYamcsConfig)
    add_fprime_subdirectory("${CMAKE_CURRENT_LIST_DIR}/LocalYamcsConfig/")
else()
    set(NEUTRON2_DEPLOYMENT_CONFIG RfMvpConfig)
    add_fprime_subdirectory("${CMAKE_CURRENT_LIST_DIR}/RfMvpConfig/")
endif()
add_fprime_subdirectory("${CMAKE_CURRENT_LIST_DIR}/Top/")

# Add custom components to this specific deployment here
# add_fprime_subdirectory("${CMAKE_CURRENT_LIST_DIR}/MyComponent/")

register_fprime_deployment(
    SOURCES
        "${CMAKE_CURRENT_LIST_DIR}/Main.cpp"
    DEPENDS
        ${FPRIME_CURRENT_MODULE}_Top
)
