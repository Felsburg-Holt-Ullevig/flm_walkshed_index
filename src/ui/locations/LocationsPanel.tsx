import { type FormEvent, useEffect, useRef, useState } from 'react';
import { inBounds, type Location, MAX_LOCATIONS } from '../../domain/locations';

interface LocationsPanelProps {
  locations: readonly Location[];
  selectedId: string | null;
  addMode: boolean;
  undoChange: string | undefined;
  redoChange: string | undefined;
  onToggleAddMode: () => void;
  onAddAtCentre: () => void;
  onSelect: (id: string | null) => void;
  onZoomTo: (location: Location) => void;
  onEdit: (id: string, name: string, lng: number, lat: number) => void;
  onRemove: (id: string) => void;
  onUndo: () => void;
  onRedo: () => void;
  onClear: () => void;
}

const coord = (value: number) => value.toFixed(5);

function EditForm({
  location,
  onSave,
  onCancel,
}: {
  location: Location;
  onSave: (name: string, lng: number, lat: number) => void;
  onCancel: () => void;
}) {
  const [name, setName] = useState(location.name);
  const [lat, setLat] = useState(coord(location.lat));
  const [lng, setLng] = useState(coord(location.lng));
  const [error, setError] = useState<string | null>(null);
  const first = useRef<HTMLInputElement>(null);
  useEffect(() => first.current?.focus(), []);
  const errorId = `edit-error-${location.id}`;

  const submit = (event: FormEvent) => {
    event.preventDefault();
    // Unchanged fields keep full precision rather than the five decimals shown.
    const latValue = lat === coord(location.lat) ? location.lat : Number(lat);
    const lngValue = lng === coord(location.lng) ? location.lng : Number(lng);
    if (name.trim() === '') return setError('Enter a name.');
    if (lat.trim() === '' || lng.trim() === '' || !inBounds(lngValue, latValue))
      return setError('Enter a latitude and longitude in or near Colorado.');
    onSave(name, lngValue, latValue);
  };

  return (
    <form className="location-edit" onSubmit={submit} noValidate>
      <label>
        Name
        <input ref={first} value={name} onChange={(e) => setName(e.currentTarget.value)} />
      </label>
      <label>
        Latitude
        <input
          inputMode="decimal"
          value={lat}
          aria-describedby={error ? errorId : undefined}
          onChange={(e) => setLat(e.currentTarget.value)}
        />
      </label>
      <label>
        Longitude
        <input
          inputMode="decimal"
          value={lng}
          aria-describedby={error ? errorId : undefined}
          onChange={(e) => setLng(e.currentTarget.value)}
        />
      </label>
      {error && (
        <p id={errorId} className="field-error" role="alert">
          {error}
        </p>
      )}
      <div className="button-row">
        <button type="submit">Save</button>
        <button type="button" onClick={onCancel}>
          Cancel
        </button>
      </div>
    </form>
  );
}

export function LocationsPanel(props: LocationsPanelProps) {
  const { locations, selectedId, addMode } = props;
  const [editingId, setEditingId] = useState<string | null>(null);
  const full = locations.length >= MAX_LOCATIONS;
  const selectedRow = useRef<HTMLLIElement>(null);

  useEffect(() => {
    if (selectedId) selectedRow.current?.scrollIntoView({ block: 'nearest' });
    if (selectedId !== editingId) setEditingId(null);
  }, [selectedId, editingId]);

  return (
    <section className="locations" aria-labelledby="locations-heading">
      <h2 id="locations-heading">
        Locations{' '}
        <span className="count">
          ({locations.length} of {MAX_LOCATIONS})
        </span>
      </h2>
      <div className="button-row">
        <button
          type="button"
          aria-pressed={addMode}
          disabled={full && !addMode}
          onClick={props.onToggleAddMode}
        >
          Add on map
        </button>
        <button type="button" disabled={full} onClick={props.onAddAtCentre}>
          Add at centre
        </button>
      </div>
      <div className="button-row">
        <button
          type="button"
          disabled={!props.undoChange}
          aria-label={props.undoChange ? `Undo: ${props.undoChange}` : 'Undo'}
          title={props.undoChange ? `Undo: ${props.undoChange}` : undefined}
          onClick={props.onUndo}
        >
          Undo
        </button>
        <button
          type="button"
          disabled={!props.redoChange}
          aria-label={props.redoChange ? `Redo: ${props.redoChange}` : 'Redo'}
          title={props.redoChange ? `Redo: ${props.redoChange}` : undefined}
          onClick={props.onRedo}
        >
          Redo
        </button>
        <button type="button" disabled={locations.length === 0} onClick={props.onClear}>
          Clear
        </button>
      </div>
      {full && <p className="hint">The maximum of {MAX_LOCATIONS} locations is reached.</p>}
      {locations.length === 0 ? (
        <p className="hint">No locations yet.</p>
      ) : (
        <ol className="location-list">
          {locations.map((location, index) => {
            const selected = location.id === selectedId;
            return (
              <li
                key={location.id}
                ref={selected ? selectedRow : undefined}
                data-selected={selected || undefined}
              >
                <button
                  type="button"
                  className="location-row"
                  aria-pressed={selected}
                  onClick={() => props.onSelect(selected ? null : location.id)}
                >
                  <span className="location-number" aria-hidden="true">
                    {index + 1}
                  </span>
                  <span>
                    <span className="location-name">{location.name}</span>
                    <span className="location-coords">
                      {coord(location.lat)}, {coord(location.lng)}
                    </span>
                  </span>
                </button>
                {selected && editingId !== location.id && (
                  <div className="button-row location-actions">
                    <button type="button" onClick={() => setEditingId(location.id)}>
                      Edit
                    </button>
                    <button type="button" onClick={() => props.onZoomTo(location)}>
                      Zoom to
                    </button>
                    <button type="button" onClick={() => props.onRemove(location.id)}>
                      Delete
                    </button>
                  </div>
                )}
                {selected && editingId === location.id && (
                  <EditForm
                    location={location}
                    onSave={(name, lng, lat) => {
                      props.onEdit(location.id, name, lng, lat);
                      setEditingId(null);
                    }}
                    onCancel={() => setEditingId(null)}
                  />
                )}
              </li>
            );
          })}
        </ol>
      )}
    </section>
  );
}
