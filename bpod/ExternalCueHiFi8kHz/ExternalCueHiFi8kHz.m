function ExternalCueHiFi8kHz
% Bpod protocol: play an 8 kHz HiFi cue whenever Nano cue TTL arrives.
%
% Wiring:
%   Water Nano D11 cue TTL -> Bpod BNC1 input
%   Bpod HiFi module connected as HiFi1
%
% This keeps cue timing inside the Bpod state machine instead of routing the
% trigger through PC soft code.

global BpodSystem

S = BpodSystem.ProtocolSettings;
if isempty(fieldnames(S))
    S.GUI.SessionDuration_s = 3600;
    S.GUI.CueDuration_s = 0.08;
    S.GUI.CueFrequency_Hz = 8000;
    S.GUI.SamplingRate_Hz = 96000;
    S.GUI.DigitalAttenuation_dB = -30;
end

BpodParameterGUI('init', S);

% If needed, set this once in the Bpod console before running:
%   BpodSystem.ModuleUSB.HiFi1 = 'COMx';
BpodSystem.assertModule('HiFi', 1);

H = BpodHiFi(BpodSystem.ModuleUSB.HiFi1);
H.SamplingRate = S.GUI.SamplingRate_Hz;
H.DigitalAttenuation_dB = S.GUI.DigitalAttenuation_dB;

t = 0:1/S.GUI.SamplingRate_Hz:S.GUI.CueDuration_s;
tone = 0.5 * sin(2*pi*S.GUI.CueFrequency_Hz*t);
H.load(1, tone);
H.push;

% State machine messages are zero-indexed: sound slot 1 is played as ['P' 0].
LoadSerialMessages('HiFi1', {['P' 0]});

sma = NewStateMachine();
sma = SetGlobalTimer(sma, 'TimerID', 1, 'Duration', S.GUI.SessionDuration_s);

sma = AddState(sma, 'Name', 'StartSession', ...
    'Timer', 0, ...
    'StateChangeConditions', {'Tup', 'WaitingForNanoCue'}, ...
    'OutputActions', {'GlobalTimerTrig', 1});

sma = AddState(sma, 'Name', 'WaitingForNanoCue', ...
    'Timer', 0, ...
    'StateChangeConditions', {'BNC1High', 'PlayCue', 'GlobalTimer1_End', 'exit'}, ...
    'OutputActions', {});

sma = AddState(sma, 'Name', 'PlayCue', ...
    'Timer', S.GUI.CueDuration_s, ...
    'StateChangeConditions', {'Tup', 'WaitingForNanoCue', 'GlobalTimer1_End', 'exit'}, ...
    'OutputActions', {'HiFi1', 1});

SendStateMachine(sma);
RawEvents = RunStateMachine;
BpodSystem.Data.RawEvents = RawEvents;
SaveBpodProtocolSettings;
SaveBpodSessionData;

clear H
end
