#ifndef StageDir
  #error StageDir tanımlanmalıdır
#endif
#ifndef ProductVersion
  #define ProductVersion "0.2.0.dev4"
#endif
#ifndef ReleaseDir
  #define ReleaseDir "."
#endif

[Setup]
AppId={{64B670AD-5823-46E1-A5B6-A9ED7E7E46DB}
AppName=R Agents
AppVersion={#ProductVersion}
VersionInfoVersion=0.2.0.0
AppPublisher=R Agents contributors
DefaultDirName={localappdata}\Programs\RAgents
PrivilegesRequired=lowest
ArchitecturesAllowed=x64os
ArchitecturesInstallIn64BitMode=x64os
MinVersion=10.0.22000
DisableProgramGroupPage=yes
DisableDirPage=auto
UninstallDisplayName=R Agents
OutputDir={#ReleaseDir}
OutputBaseFilename=R-Agents-{#ProductVersion}-windows-x64
Compression=lzma2/fast
SolidCompression=no
ChangesEnvironment=yes
SetupLogging=yes
LicenseFile={#StageDir}\versions\{#ProductVersion}\LICENSE

[Languages]
Name: "turkish"; MessagesFile: "compiler:Languages\Turkish.isl"

[Files]
Source: "{#StageDir}\versions\{#ProductVersion}\*"; DestDir: "{app}\versions\{#ProductVersion}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "{#StageDir}\ragents.exe"; DestDir: "{app}"; Flags: onlyifdoesntexist
Source: "{#StageDir}\R-Agents.exe"; DestDir: "{app}"; Flags: onlyifdoesntexist

[Registry]
Root: HKCU; Subkey: "Software\R Agents"; ValueType: string; ValueName: "ProfileRoot"; ValueData: "{code:ProfileRoot}"; Flags: uninsdeletevalue
Root: HKCU; Subkey: "Software\R Agents"; ValueType: string; ValueName: "InstallRoot"; ValueData: "{app}"; Flags: uninsdeletevalue

[Code]
function ProfileRoot(Param: String): String;
begin
  Result := ExpandConstant('{param:PROFILE|}');
  if Result = '' then
    if not RegQueryStringValue(HKCU, 'Software\R Agents', 'ProfileRoot', Result) then
      Result := ExpandConstant('{localappdata}\RAgents\profiles\default');
end;

procedure CurStepChanged(CurStep: TSetupStep);
var
  ExitCode: Integer;
  Arguments, ExistingPath, AppPath: String;
begin
  if CurStep = ssPostInstall then begin
    Arguments := '-I -B -m ragents installation activate --root ' + AddQuotes(ProfileRoot('')) +
      ' --installation-root ' + AddQuotes(ExpandConstant('{app}')) + ' --version {#ProductVersion}';
    if not Exec(ExpandConstant('{app}\versions\{#ProductVersion}\python\python.exe'), Arguments, '', SW_HIDE,
      ewWaitUntilTerminated, ExitCode) then
      RaiseException('R Agents sağlık kontrolü başlatılamadı.');
    if ExitCode <> 0 then
      RaiseException('Yeni sürüm etkinleştirilemedi. Önceki sürüm ve profil yedeği korunuyor.');
    AppPath := ExpandConstant('{app}');
    RegQueryStringValue(HKCU, 'Environment', 'Path', ExistingPath);
    if Pos(';' + Lowercase(AppPath) + ';', ';' + Lowercase(ExistingPath) + ';') = 0 then begin
      if (ExistingPath <> '') and (Copy(ExistingPath, Length(ExistingPath), 1) <> ';') then
        ExistingPath := ExistingPath + ';';
      RegWriteExpandStringValue(HKCU, 'Environment', 'Path', ExistingPath + AppPath);
    end;
  end;
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  Version: AnsiString;
  ExitCode: Integer;
  Python, Arguments, ExistingPath, AppPath: String;
begin
  if CurUninstallStep = usUninstall then begin
    if LoadStringFromFile(ExpandConstant('{app}\current.txt'), Version) then begin
      Python := ExpandConstant('{app}\versions\') + Trim(String(Version)) + '\python\python.exe';
      Arguments := '-I -B -m ragents service --root ' + AddQuotes(ProfileRoot('')) + ' uninstall';
      Exec(Python, Arguments, '', SW_HIDE, ewWaitUntilTerminated, ExitCode);
    end;
    RegQueryStringValue(HKCU, 'Environment', 'Path', ExistingPath);
    AppPath := ExpandConstant('{app}');
    StringChangeEx(ExistingPath, AppPath + ';', '', True);
    StringChangeEx(ExistingPath, ';' + AppPath, '', True);
    if CompareText(ExistingPath, AppPath) = 0 then ExistingPath := '';
    RegWriteExpandStringValue(HKCU, 'Environment', 'Path', ExistingPath);
    DeleteFile(ExpandConstant('{app}\current.txt'));
  end;
end;
