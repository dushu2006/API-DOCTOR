import React, { useState, useRef, useEffect } from 'react';
import TopBar from './components/TopBar';
import ActivityBar from './components/ActivityBar';
import Explorer from './components/Explorer';
import EditorRegion from './components/EditorRegion';
import APIDoctorPanel from './components/APIDoctorPanel';
import BottomPanel from './components/BottomPanel';
import CommandPalette from './components/CommandPalette';
import StateToolbar from './components/StateToolbar';
import './index.css';

export default function App() {
  // Global State
  const [currentState, setCurrentState] = useState('idle'); // 'idle' | 'diagnosing' | 'fix_proposed' | 'verified_pr'
  const [selectedFile, setSelectedFile] = useState('app/demo_api/bugs.py');
  const [activeActivityTab, setActiveActivityTab] = useState('explorer');
  const [activeBottomTab, setActiveBottomTab] = useState('terminal');
  
  // Panel Visibility
  const [isExplorerOpen, setIsExplorerOpen] = useState(true);
  const [isDoctorOpen, setIsDoctorOpen] = useState(true);
  const [isBottomCollapsed, setIsBottomCollapsed] = useState(false);
  const [isDiffMode, setIsDiffMode] = useState(false);
  const [isCommandPaletteOpen, setIsCommandPaletteOpen] = useState(false);

  // Resizable Widths / Heights
  const [explorerWidth, setExplorerWidth] = useState(240);
  const [doctorWidth, setDoctorWidth] = useState(380);
  const [bottomHeight, setBottomHeight] = useState(220);

  // File status mappings
  const fileStatuses = {
    'app/demo_api/bugs.py': currentState === 'diagnosing' ? 'reading' : (currentState === 'verified_pr' ? 'modified' : 'analyzed'),
    'app/demo_api/checkout.py': 'analyzed',
    'app/routes/payments.py': 'analyzed',
    'requirements.txt': 'analyzed'
  };

  // Drag handles resize logic
  const isDraggingExplorer = useRef(false);
  const isDraggingDoctor = useRef(false);
  const isDraggingBottom = useRef(false);

  useEffect(() => {
    const handleMouseMove = (e) => {
      if (isDraggingExplorer.current) {
        const newWidth = Math.min(Math.max(e.clientX - 48, 160), 450);
        setExplorerWidth(newWidth);
      } else if (isDraggingDoctor.current) {
        const newWidth = Math.min(Math.max(window.innerWidth - e.clientX, 280), 550);
        setDoctorWidth(newWidth);
      } else if (isDraggingBottom.current) {
        const newHeight = Math.min(Math.max(window.innerHeight - e.clientY, 80), 500);
        setBottomHeight(newHeight);
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
      {/* Fixed 44px Top Bar */}
      <TopBar 
        currentState={currentState} 
        setCurrentState={setCurrentState} 
      />

      {/* Main Workspace Workspace Canvas */}
      <div style={{ flex: 1, display: 'flex', flexDirection: 'column', overflow: 'hidden', position: 'relative' }}>
        
        {/* Upper Region (Activity Bar + Explorer + Editor + API Doctor Panel) */}
        <div style={{ flex: 1, display: 'flex', overflow: 'hidden', width: '100%' }}>
          
          {/* Left Activity Bar */}
          <ActivityBar 
            activeTab={activeActivityTab}
            setActiveTab={setActiveActivityTab}
            isDoctorOpen={isDoctorOpen}
            setIsDoctorOpen={setIsDoctorOpen}
            isExplorerOpen={isExplorerOpen}
            setIsExplorerOpen={setIsExplorerOpen}
            hasActiveIncident={currentState !== 'idle'}
          />

          {/* Left Explorer Panel */}
          <Explorer 
            selectedFile={selectedFile}
            setSelectedFile={setSelectedFile}
            fileStatuses={fileStatuses}
            explorerWidth={explorerWidth}
            setExplorerWidth={setExplorerWidth}
            isExplorerOpen={isExplorerOpen}
          />

          {/* Explorer Drag Handle */}
          {isExplorerOpen && (
            <div 
              className="resize-handle-col"
              onMouseDown={(e) => {
                isDraggingExplorer.current = true;
                document.body.style.cursor = 'col-resize';
              }}
            />
          )}

          {/* Center Editor Region */}
          <EditorRegion 
            selectedFile={selectedFile}
            setSelectedFile={setSelectedFile}
            currentState={currentState}
            isDiffMode={isDiffMode}
            setIsDiffMode={setIsDiffMode}
          />

          {/* API Doctor Drag Handle */}
          {isDoctorOpen && (
            <div 
              className="resize-handle-col"
              onMouseDown={(e) => {
                isDraggingDoctor.current = true;
                document.body.style.cursor = 'col-resize';
              }}
            />
          )}

          {/* Right API Doctor Panel */}
          <APIDoctorPanel 
            currentState={currentState}
            setCurrentState={setCurrentState}
            doctorWidth={doctorWidth}
            isDoctorOpen={isDoctorOpen}
            setIsDoctorOpen={setIsDoctorOpen}
            setSelectedFile={setSelectedFile}
            setIsDiffMode={setIsDiffMode}
          />
        </div>

        {/* Bottom Panel Drag Handle */}
        {!isBottomCollapsed && (
          <div 
            className="resize-handle-row"
            onMouseDown={(e) => {
              isDraggingBottom.current = true;
              document.body.style.cursor = 'row-resize';
            }}
          />
        )}

        {/* Bottom Resizable Panel */}
        <BottomPanel 
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
        setCurrentState={setCurrentState}
        setIsDiffMode={setIsDiffMode}
        setActiveBottomTab={setActiveBottomTab}
      />

      {/* Floating State Simulator Toolbar */}
      <StateToolbar 
        currentState={currentState}
        setCurrentState={setCurrentState}
        onOpenCommandPalette={() => setIsCommandPaletteOpen(true)}
      />
    </div>
  );
}
