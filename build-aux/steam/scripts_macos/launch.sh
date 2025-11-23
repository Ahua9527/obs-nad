#!/bin/zsh

arch_name="${CPUTYPE}"
is_translated="$(sysctl -in sysctl.proc_translated)"

if (( is_translated )) arch_name="arm64"
if [[ ${@} == *'--intel'* ]] arch_name="x86_64"

# Detect app bundle name dynamically (no `local` at top level; zsh would error)
app_bundle_path=(OBS\ Studio-*.app(N[1]))
if [[ ${#app_bundle_path} -eq 0 ]]; then
  # Fallback to OBS.app if OBS Studio-*.app not found
  app_bundle_path=(OBS.app(N[1]))
fi
if [[ ${#app_bundle_path} -eq 0 ]]; then
  # If not found in current directory, try architecture subdirectories
  if [[ -d "${arch_name}" ]]; then
    app_bundle_path=(${arch_name}/OBS\ Studio-*.app(N[1]))
    if [[ ${#app_bundle_path} -eq 0 ]]; then
      # Fallback to OBS.app in architecture subdirectory
      app_bundle_path=(${arch_name}/OBS.app(N[1]))
    fi
  fi
fi

if [[ ${#app_bundle_path} -eq 0 ]]; then
  echo "Error: No OBS Studio app bundle found (tried patterns: OBS Studio-*.app, OBS.app)"
  exit 1
fi

app_bundle="${app_bundle_path:t}"

if [[ -d "${app_bundle}" ]]; then
  exec open "${app_bundle}" -W --args "${@}"
fi

case ${arch_name} {
    x86_64) exec open "x86_64/${app_bundle}" -W --args "${@}" ;;
    arm64) exec open "arm64/${app_bundle}" -W --args "${@}" ;;
    *) echo "Unknown architecture: ${arch_name}"; exit 2 ;;
}
