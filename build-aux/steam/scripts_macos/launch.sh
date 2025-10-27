#!/bin/zsh
 
arch_name="${CPUTYPE}"
is_translated="$(sysctl -in sysctl.proc_translated)"

if (( is_translated )) arch_name="arm64"
if [[ ${@} == *'--intel'* ]] arch_name="x86_64"
app_bundle="OBS Studio-no-aja.app"

if [[ -d "${app_bundle}" ]] exec open "${app_bundle}" -W --args "${@}"

case ${arch_name} {
    x86_64) exec open "x86_64/${app_bundle}" -W --args "${@}" ;;
    arm64) exec open "arm64/${app_bundle}" -W --args "${@}" ;;
    *) echo "Unknown architecture: ${arch_name}"; exit 2 ;;
}
