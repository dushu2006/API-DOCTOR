import React, { useState, useRef, useEffect, useCallback } from 'react';
import TopBar from './components/TopBar';
import ActivityBar from './components/ActivityBar';
import Explorer from './components/Explorer';
import EditorRegion from './components/EditorRegion';
import APIDoctorPanel from './components/APIDoctorPanel';
import BottomPanel from './components/BottomPanel';
import CommandPalette from './components/CommandPalette';
import { api } from './api';
import './index.css';

export default function App() {
  // Real Backend Data States
  const [isBackendConnected, setIsBackendConnected] = useState(false);
  const [incidentsList, setIncidentsList] = useState([]);
  const [activeIncidentId, setActiveIncidentId] = useState(null);
  
  // Active Incident Detailed Payload Objects
  const [activeIncident, setActiveIncident] = useState(null);
  const [incidentContext, setIncidentContext] = useState(null);
  const [incidentDiff, setIncidentDiff] = useState(null);
  const [incidentSandbox, setIncidentSandbox] = useState(null);
  const [incidentPR, setIncidentPR] = useState(null);
  const [timelineEvents, setTimelineEvents] = useState([]);
  const [isDiagnosing, setIsDiagnosing] = useState(false);

  // Layout & Visibility
  const [selectedFile, setSelectedFile] = useState('app/demo_api/bugs.py');
  const [activeActivityTab, setActiveActivityTab] = useState('explorer');
  const [activeBottomTab, setActiveBottomTab] = useState('terminal');
  const [isExplorerOpen, setIsExplorerOpen] = useState(true);
  const [isDoctorOpen, setIsDoctorOpen] = useState(true);
  const [isBottomCollapsed, setIsBottomCollapsed] = useState(false);
  const [isDiffMode, setIsDiffMode] = useState(false);
  const [isCommandPaletteOpen, setIsCommandPaletteOpen] = useState(false);

  // Resizable widths
  const [explorerWidth, setExplorerWidth] = useState(240);
  const [doctorWidth, setDoctorWidth] = useState(380);
  const [bottomHeight, setBottomHeight] = useState(220);

  // Check Backend Health & Fetch Incident History on mount
  const refreshBackendState = useCallback(async () => {
    try {
      const health = await api.getHealth();
      setIsBackendConnected(health.status === 'ok');

      const incidents = await api.listIncidents();
      setIncidentsList(incidents || []);
      
      if (!activeIncidentId && incidents && incidents.length > 0) {
        setActiveIncidentId(incidents[0].id);
      }
    } catch (err) {
      setIsBackendConnected(false);
    }
  }, [activeIncidentId]);

  useEffect(() => {
    refreshBackendState();
    const interval = setInterval(refreshBackendState, 5000);
    return () => clearInterval(interval);
  }, [refreshBackendState]);

  // Fetch full details whenever activeIncidentId changes
  const fetchIncidentDetails = useCallback(async (id) => {
    if (!id) return;
    try {
      const [inc, ctx, diff, sb, pr] = await Promise.allSettled([
        api.getIncident(id),
        api.getIncidentContext(id),
        api.getIncidentDiff(id),
        api.getIncidentSandbox(id),
        api.getIncidentPR(id)
      ]);

      if (inc.status === 'fulfilled') {
        setActiveIncident(inc.value);
        setIsDiagnosing(!inc.value.status?.includes('VERIFIED') && !inc.value.status?.includes('PR') && !inc.value.status?.includes('FAILED') && inc.value.status !== 'REPAIR_LIMIT_REACHED');
      }
      if (ctx.status === 'fulfilled') setIncidentContext(ctx.value);
      if (diff.status === 'fulfilled') setIncidentDiff(diff.value);
      if (sb.status === 'fulfilled') setIncidentSandbox(sb.value);
      if (pr.status === 'fulfilled') setIncidentPR(pr.value);
    } catch (err) {
      console.error('Failed to fetch incident details:', err);
    }
  }, []);

  useEffect(() => {
    if (activeIncidentId) {
      fetchIncidentDetails(activeIncidentId);
    }
  }, [activeIncidentId, fetchIncidentDetails]);

  // Subscribe to real-time SSE stream for active incident
  useEffect(() => {
    if (!activeIncidentId) return;
    setTimelineEvents([]);

    const unsubscribe = api.subscribeIncidentStream(
      activeIncidentId,
      (eventData) => {
        if (eventData.step || eventData.message) {
          setTimelineEvents(prev => [...prev, eventData]);
        }
        // Periodically refresh incident detail upon event
        fetchIncidentDetails(activeIncidentId);
      },
      (err) => console.log('SSE Stream closed')
    );

    return () => unsubscribe();
  }, [activeIncidentId, fetchIncidentDetails]);

  // Workflow Handlers
  const handleStartDiagnosis = async (scenario = 'null_pointer') => {
    try {
      setIsDiagnosing(true);
      const res = await api.triggerScenario(scenario);
      if (res && res.incident_id) {
        setActiveIncidentId(res.incident_id);
        await refreshBackendState();
        fetchIncidentDetails(res.incident_id);
      }
    } catch (err) {
      alert(`Failed to start diagnosis on backend: ${err.message}`);
      setIsDiagnosing(false);
    }
  };

  const handleStopDiagnosis = () => {
    setIsDiagnosing(false);
  };

  const handleApproveFix = async (approved) => {
    if (!activeIncidentId) return;
    try {
      await api.approveFix(activeIncidentId, approved);
      await fetchIncidentDetails(activeIncidentId);
    } catch (err) {
      alert(`Failed to approve fix: ${err.message}`);
    }
  };

  const handleCreatePR = async () => {
    if (!activeIncidentId) return;
    try {
      await api.createPR(activeIncidentId);
      await fetchIncidentDetails(activeIncidentId);
    } catch (err) {
      alert(`Failed to create PR: ${err.message}`);
    }
  };

  // Drag handle resize logic
  const isDraggingExplorer = useRef(false);
  const isDraggingDoctor = useRef(false);
  const isDraggingBottom = useRef(false);

  useEffect(() => {
    const handleMouseMove = (e) => {
      if (isDraggingExplorer.current) {
        setExplorerWidth(Math.min(Math.max(e.clientX - 48, 160), 450));
      } else if (isDraggingDoctor.current) {
        setDoctorWidth(Math.min(Math.max(window.innerWidth - e.clientX, 280), 550));
      } else if (isDraggingBottom.current) {
        setBottomHeight(Math.min(Math.max(window.innerHeight - e.clientY, 80), 500));
      }
    };

    const handleMouseUp = () => {
      isDraggingExplorer.current = false;
      isDraggingDoctor.current = false;
      isDraggingBottom.current = false;
      document.body.style.cursor = 'default';
    };

    window.addEventListener('mousemove', handleMouseMove);
    window.addEventListener('mouseup', handleMouseUp);
    return () => {
      window.removeEventListener('mousemove', handleMouseMove);
      window.removeEventListener('mouseup', handleMouseUp);
    };
  }, []);

  return (
    <div style={{ display: 'flex', flexDirection: 'column', width: '100vw', height: '100vh', overflow: 'hidden' }}>
      {/* Top Bar with real backend connection & scenario triggers */}
      <TopBar 
        activeIncident={activeIncident}
        onStartDiagnosis={handleStartDiagnosis}
        onStopDiagnosis={handleStopDiagnosis}
        isDiagnosing={isDiagnosing}
        isBackendConnected={isBackendConnected}
      />

      {/* Main Workspace Canvas */}
      <div style={{ flex: 1, display: 'flex', flexDirection: 'column', overflow: 'hidden', position: 'relative' }}>
        
        {/* Upper Region */}
        <div style={{ flex: 1, display: 'flex', overflow: 'hidden', width: '100%' }}>
          
          <ActivityBar 
            activeTab={activeActivityTab}
            setActiveTab={setActiveActivityTab}
            isDoctorOpen={isDoctorOpen}
            setIsDoctorOpen={setIsDoctorOpen}
            isExplorerOpen={isExplorerOpen}
            setIsExplorerOpen={setIsExplorerOpen}
            hasActiveIncident={Boolean(activeIncident)}
          />

          <Explorer 
            selectedFile={selectedFile}
            setSelectedFile={setSelectedFile}
            fileStatuses={{
              [selectedFile]: isDiagnosing ? 'reading' : (incidentDiff?.present ? 'modified' : 'analyzed')
            }}
            explorerWidth={explorerWidth}
            setExplorerWidth={setExplorerWidth}
            isExplorerOpen={isExplorerOpen}
          />

          {isExplorerOpen && (
            <div 
              className="resize-handle-col"
              onMouseDown={() => {
                isDraggingExplorer.current = true;
                document.body.style.cursor = 'col-resize';
              }}
            />
          )}

          <EditorRegion 
            selectedFile={selectedFile}
            setSelectedFile={setSelectedFile}
            incidentContext={incidentContext}
            incidentDiff={incidentDiff}
            isDiagnosing={isDiagnosing}
            isDiffMode={isDiffMode}
            setIsDiffMode={setIsDiffMode}
          />

          {isDoctorOpen && (
            <div 
              className="resize-handle-col"
              onMouseDown={() => {
                isDraggingDoctor.current = true;
                document.body.style.cursor = 'col-resize';
              }}
            />
          )}

          <APIDoctorPanel 
            incidentsList={incidentsList}
            activeIncident={activeIncident}
            incidentContext={incidentContext}
            incidentDiff={incidentDiff}
            incidentSandbox={incidentSandbox}
            incidentPR={incidentPR}
            timelineEvents={timelineEvents}
            isDiagnosing={isDiagnosing}
            onStartDiagnosis={handleStartDiagnosis}
            onApproveFix={handleApproveFix}
            onCreatePR={handleCreatePR}
            onSelectIncident={(id) => setActiveIncidentId(id)}
            doctorWidth={doctorWidth}
            isDoctorOpen={isDoctorOpen}
            setIsDoctorOpen={setIsDoctorOpen}
            setSelectedFile={setSelectedFile}
            setIsDiffMode={setIsDiffMode}
          />
        </div>

        {!isBottomCollapsed && (
          <div 
            className="resize-handle-row"
            onMouseDown={() => {
              isDraggingBottom.current = true;
              document.body.style.cursor = 'row-resize';
            }}
          />
        )}

        <BottomPanel 
          activeIncident={activeIncident}
          incidentContext={incidentContext}
          incidentDiff={incidentDiff}
          incidentSandbox={incidentSandbox}
          activeBottomTab={activeBottomTab}
          setActiveBottomTab={setActiveBottomTab}
          bottomHeight={bottomHeight}
          setBottomHeight={setBottomHeight}
          isBottomCollapsed={isBottomCollapsed}
          setIsBottomCollapsed={setIsBottomCollapsed}
        />
      </div>

      {/* Command Palette (⌘K) */}
      <CommandPalette 
        isOpen={isCommandPaletteOpen}
        onClose={(val) => setIsCommandPaletteOpen(typeof val === 'boolean' ? val : false)}
        setCurrentState={() => handleStartDiagnosis('null_pointer')}
        setIsDiffMode={setIsDiffMode}
        setActiveBottomTab={setActiveBottomTab}
      />
    </div>
  );
}
