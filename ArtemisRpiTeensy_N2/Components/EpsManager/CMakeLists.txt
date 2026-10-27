register_fprime_library(
    AUTOCODER_INPUTS
        ${CMAKE_CURRENT_LIST_DIR}/EpsManager.fpp
    SOURCES
        ${CMAKE_CURRENT_LIST_DIR}/EpsManager.cpp
    DEPENDS
        Components_Types
)

set(UT_SOURCE_FILES
    ${CMAKE_CURRENT_LIST_DIR}/EpsManager.fpp
    ${CMAKE_CURRENT_LIST_DIR}/test/ut/EpsManagerTestMain.cpp
    ${CMAKE_CURRENT_LIST_DIR}/test/ut/EpsManagerTester.cpp
)

set(UT_MOD_DEPS
    Components_Types
    Components_LinkCfg
    STest
)

set(UT_AUTO_HELPERS ON)
register_fprime_ut()
