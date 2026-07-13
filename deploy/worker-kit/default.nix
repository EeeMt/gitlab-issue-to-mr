let
  nixpkgsLock = builtins.fromJSON (builtins.readFile ./nixpkgs.json);
  pinnedNixpkgs = builtins.fetchTarball {
    inherit (nixpkgsLock) url sha256;
  };
in
{ pkgs ? import pinnedNixpkgs {} }:

let
  codegraphPlatformPackage =
    if pkgs.stdenv.hostPlatform.isAarch64
    then "@colbymchenry/codegraph-linux-arm64"
    else "@colbymchenry/codegraph-linux-x64";
  nodeTools = pkgs.buildNpmPackage {
    pname = "codify-worker-kit-node-tools";
    version = "0.1.0";
    src = ./npm;
    npmDepsHash = "sha256-gj677HBaLczVrzMxv+2SaRgkKMCRrTpktpVxUftHOpc=";
    dontNpmBuild = true;
    installPhase = ''
      runHook preInstall
      mkdir -p $out/lib/codify-node-tools
      cp -R node_modules $out/lib/codify-node-tools/
      rm -f $out/lib/codify-node-tools/node_modules/${codegraphPlatformPackage}/node
      cp ${./validate_mermaid_summary.mjs} \
        $out/lib/codify-node-tools/validate_mermaid_summary.mjs
      runHook postInstall
    '';
  };
in
pkgs.symlinkJoin {
  name = "codify-worker-kit-runtime";
  passthru = {
    nixpkgsRevision = nixpkgsLock.rev;
    nixpkgsVersion = pkgs.lib.version;
  };
  paths = [
    pkgs.bashInteractive
    pkgs.cacert
    pkgs.coreutils
    pkgs.curl
    pkgs.findutils
    pkgs.gawk
    pkgs.git
    pkgs.gnugrep
    pkgs.gnused
    pkgs.gnutar
    pkgs.gzip
    pkgs.jq
    pkgs.nodejs_22
    pkgs.openssh
    pkgs.python312
    pkgs.ripgrep
    pkgs.which
    nodeTools
  ];
  nativeBuildInputs = [ pkgs.makeWrapper ];
  postBuild = ''
    rm -f $out/bin/codegraph
    makeWrapper ${pkgs.nodejs_22}/bin/node $out/bin/codegraph \
      --add-flags "$out/lib/codify-node-tools/node_modules/${codegraphPlatformPackage}/lib/dist/bin/codegraph.js"
    makeWrapper ${pkgs.nodejs_22}/bin/node $out/bin/codify-validate-mermaid \
      --add-flags "$out/lib/codify-node-tools/validate_mermaid_summary.mjs"
  '';
}
