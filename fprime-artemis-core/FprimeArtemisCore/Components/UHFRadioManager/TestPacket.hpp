#pragma once
#include <cstdint>
namespace RadioLink {
// Raw channel-0 bench marker, including LF and excluding a C string terminator.
constexpr uint8_t TEST_PACKET[] = {'A','R','T','E','M','I','S','-','R','A','D','I','O','-','T','E','S','T','\n'};
}
