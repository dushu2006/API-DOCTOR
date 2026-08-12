import React, { useState } from 'react';
import { 
  ChevronDown, 
  ChevronRight, 
  FileCode, 
  FileText, 
  FileLock, 
  Folder, 
  FolderOpen, 
  RotateCw, 
  FilePlus, 
  Minimize2,
  Search,
  CheckCircle2
} from 'lucide-react';

export default function Explorer({ 
  selectedFile, 
  setSelectedFile, 
  fileStatuses, 
  explorerWidth, 
  setExplorerWidth,
  isExplorerOpen 
}) {
  const [searchQuery, setSearchQuery] = useState('');
  const [openFolders, setOpenFolders] = useState({ 'app': true, 'demo_api': true, 'routes': true });
  const [contextMenu, setContextMenu] = useState(null);

  if (!isExplorerOpen) return null;

  const toggleFolder = (folderKey) => {
    setOpenFolders(prev => ({ ...prev, [folderKey]: !prev[folderKey] }));
  };

  const fileTree = [
    {
      name: 'app',
      type: 'folder',
      key: 'app',
      children: [
        {
          name: 'demo_api',
          type: 'folder',
          key: 'demo_api',
          children: [
            { name: 'bugs.py', type: 'file', ext: 'py', path: 'app/demo_api/bugs.py' },
            { name: 'checkout.py', type: 'file', ext: 'py', path: 'app/demo_api/checkout.py' },
            { name: 'main.py', type: 'file', ext: 'py', path: 'app/demo_api/main.py' },
          ]
        },
        {
          name: 'routes',
          type: 'folder',
          key: 'routes',
          children: [
            { name: 'orders.py', type: 'file', ext: 'py', path: 'app/routes/orders.py' },
            { name: 'payments.py', type: 'file', ext: 'py', path: 'app/routes/payments.py' },
          ]
        }
      ]
    },
    { name: '.env', type: 'file', ext: 'env', path: '.env' },
    { name: 'README.md', type: 'file', ext: 'md', path: 'README.md' },
    { name: 'requirements.txt', type: 'file', ext: 'txt', path: 'requirements.txt' }
  ];

  const getFileIcon = (ext) => {
    switch (ext) {
      case 'py': return <FileCode size={14} style={{ color: '#3572A5' }} />;
      case 'env': return <FileLock size={14} style={{ color: '#E8A23D' }} />;
      case 'md': return <FileText size={14} style={{ color: '#7C8CF8' }} />;
      default: return <FileText size={14} style={{ color: 'var(--text-muted)' }} />;
    }
  };

  const renderStatusSuffix = (filePath) => {
    const status = fileStatuses[filePath];
    if (!status) return null;

    if (status === 'reading') {
      return (
        <span style={{ display: 'flex', alignItems: 'center', gap: '4px', fontSize: '11px', color: 'var(--color-accent)' }}>
          <span className="agent-dot" />
          <span>reading</span>
        </span>
      );
    }
    if (status === 'modified') {
      return (
        <span style={{ display: 'flex', alignItems: 'center', gap: '4px', fontSize: '11px', color: 'var(--color-warning)' }}>
          <span style={{ width: '6px', height: '6px', borderRadius: '50%', backgroundColor: 'var(--color-warning)' }} />
          <span>modified</span>
        </span>
      );
    }
    if (status === 'analyzed') {
      return (
        <span style={{ display: 'flex', alignItems: 'center', gap: '4px', fontSize: '11px', color: 'var(--color-success)' }}>
          <CheckCircle2 size={12} />
          <span style={{ color: 'var(--text-muted)' }}>analyzed</span>
        </span>
      );
    }
    return null;
  };

  const handleContextMenu = (e, file) => {
    e.preventDefault();
    setContextMenu({
      x: e.clientX,
      y: e.clientY,
      file
    });
  };

  const renderTree = (items, depth = 0) => {
    return items.map((item) => {
      if (searchQuery && item.type === 'file' && !item.name.toLowerCase().includes(searchQuery.toLowerCase())) {
        return null;
      }

      if (item.type === 'folder') {
        const isOpen = openFolders[item.key];
        return (
          <div key={item.key}>
            <div
              onClick={() => toggleFolder(item.key)}
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: '6px',
                paddingLeft: `${depth * 14 + 12}px`,
                height: '24px',
                cursor: 'pointer',
                color: 'var(--text-primary)',
                fontSize: '12px'
              }}
              className="hover-bg"
            >
              {isOpen ? <ChevronDown size={14} style={{ color: 'var(--text-muted)' }} /> : <ChevronRight size={14} style={{ color: 'var(--text-muted)' }} />}
              {isOpen ? <FolderOpen size={14} style={{ color: '#7C8CF8' }} /> : <Folder size={14} style={{ color: 'var(--text-muted)' }} />}
              <span>{item.name}</span>
            </div>
            {isOpen && renderTree(item.children, depth + 1)}
          </div>
        );
      } else {
        const isSelected = selectedFile === item.path;
        return (
          <div
            key={item.path}
            onClick={() => setSelectedFile(item.path)}
            onContextMenu={(e) => handleContextMenu(e, item)}
            style={{
              display: 'flex',
              alignItems: 'center',
              justify: 'space-between',
              paddingLeft: `${depth * 14 + 12}px`,
              paddingRight: '12px',
              height: '26px',
              cursor: 'pointer',
              backgroundColor: isSelected ? 'var(--surface-2)' : 'transparent',
              borderLeft: isSelected ? '2px solid var(--color-accent)' : '2px solid transparent',
              color: isSelected ? 'var(--text-primary)' : 'var(--text-muted)',
              fontSize: '12px',
              fontFamily: 'var(--font-mono)'
            }}
            className="hover-bg"
          >
            <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
              {getFileIcon(item.ext)}
              <span>{item.name}</span>
            </div>
            {renderStatusSuffix(item.path)}
          </div>
        );
      }
    });
  };

  return (
    <div 
      onClick={() => setContextMenu(null)}
      style={{
        width: `${explorerWidth}px`,
        height: '100%',
        backgroundColor: 'var(--surface-1)',
        borderRight: '1px solid var(--border-color)',
        display: 'flex',
        flexDirection: 'column',
        userSelect: 'none',
        position: 'relative'
      }}
    >
      {/* Header */}
      <div style={{
        height: '35px',
        padding: '0 12px',
        display: 'flex',
        alignItems: 'center',
        justify: 'space-between',
        borderBottom: '1px solid var(--border-color)'
      }}>
        <span style={{ 
          fontSize: '11px', 
          fontWeight: 700, 
          letterSpacing: '0.08em', 
          color: 'var(--text-muted)',
          fontFamily: 'var(--font-heading)' 
        }}>
          EXPLORER
        </span>
        <div style={{ display: 'flex', gap: '8px', color: 'var(--text-muted)' }}>
          <FilePlus size={14} style={{ cursor: 'pointer' }} title="New File" />
          <RotateCw size={14} style={{ cursor: 'pointer' }} title="Refresh" />
          <Minimize2 size={14} style={{ cursor: 'pointer' }} title="Collapse Folders" />
        </div>
      </div>

      {/* Search Input */}
      <div style={{ padding: '6px 8px', borderBottom: '1px solid var(--border-color)' }}>
        <div style={{
          display: 'flex',
          alignItems: 'center',
          gap: '6px',
          backgroundColor: 'var(--surface-2)',
          border: '1px solid var(--border-color)',
          borderRadius: '4px',
          padding: '4px 8px'
        }}>
          <Search size={13} style={{ color: 'var(--text-muted)' }} />
          <input 
            type="text"
            placeholder="Search files..."
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            style={{
              background: 'none',
              border: 'none',
              color: 'var(--text-primary)',
              fontSize: '11px',
              outline: 'none',
              width: '100%',
              fontFamily: 'var(--font-mono)'
            }}
          />
        </div>
      </div>

      {/* Tree Content */}
      <div style={{ flex: 1, overflowY: 'auto', paddingTop: '4px' }}>
        {renderTree(fileTree)}
      </div>

      {/* Right Click Context Menu */}
      {contextMenu && (
        <div style={{
          position: 'fixed',
          top: contextMenu.y,
          left: contextMenu.x,
          backgroundColor: 'var(--surface-2)',
          border: '1px solid var(--border-color)',
          borderRadius: '6px',
          boxShadow: '0 8px 20px rgba(0,0,0,0.5)',
          padding: '4px 0',
          zIndex: 200,
          width: '150px',
          fontSize: '12px'
        }}>
          <div style={{ padding: '6px 12px', cursor: 'pointer' }} onClick={() => setSelectedFile(contextMenu.file.path)}>Open</div>
          <div style={{ padding: '6px 12px', cursor: 'pointer' }}>Rename</div>
          <div style={{ padding: '6px 12px', cursor: 'pointer' }}>Copy Path</div>
          <div style={{ height: '1px', backgroundColor: 'var(--border-color)', margin: '4px 0' }} />
          <div style={{ padding: '6px 12px', cursor: 'pointer', color: 'var(--color-failure)' }}>Delete</div>
        </div>
      )}
    </div>
  );
}
